import asyncpg
import asyncio
import yaml
import ROOT
from datetime import datetime
from array import array
import uproot
import matplotlib.pyplot as plt
#import argparse
#parser = argparse.ArgumentParser(description="Easy input of date.")

#parser.add_argument('--date', type=str, help="date string")
#parser.add_argument('--viewer_pwd', type=str, default='XXXXX', required=False, help="Viewer PSQL password")
#args = parser.parse_args()

# Load configuration file
configuration = {}
with open('dbase_info/conn.yaml', 'r') as file:
    configuration = yaml.safe_load(file)
#ass_date_start="2025-03-18"
async def fetch_module_info(ass_date_start,pwd):
    # instantiate db connection  
    conn = await asyncpg.connect(
            host = configuration['db_hostname'],
            database = configuration['dbname'],
            user = 'viewer', #configuration['postg']
            password = pwd #args.viewer_pwd #configuration['DBPassword']
        )
    ass_date = datetime.strptime(ass_date_start, '%Y-%m-%d').date()
    counting=f"""SELECT COUNT(*) from module_info WHERE assembled >= $1 ;"""
    actual_count=await conn.fetch(counting,ass_date)
    v_info={}
    i_info={}
    adc_stdd={}
    adc_mean={}
    query_modules=f"""SELECT module_name FROM module_info WHERE assembled >= $1 ;"""
    result= await conn.fetch(query_modules,ass_date)
    module_names_array = [row['module_name'] for row in result]
    print(module_names_array)
    for i in module_names_array:
       query_v_scan=f"""SELECT meas_v FROM module_iv_test WHERE module_name=$1 ORDER BY date_test DESC LIMIT 1;"""
       query_i_scan=f""" SELECT meas_i FROM module_iv_test WHERE module_name=$1 ORDER BY date_test DESC LIMIT 1;"""
       query_adc_mean=f"""SELECT adc_mean FROM module_pedestal_test WHERE module_name=$1 ORDER BY date_test DESC LIMIT 1;"""
       query_adc_stdd=f""" SELECT adc_stdd FROM module_pedestal_test WHERE module_name=$1 ORDER BY date_test DESC LIMIT 1;"""
       
       result_v=await conn.fetch(query_v_scan,i)
       result_i=await conn.fetch(query_i_scan,i)
       result_adc_stdd = await conn.fetch(query_adc_stdd,i)
       result_adc_mean = await conn.fetch(query_adc_mean,i)
       
       if result_v:
           v_info[i]=result_v[0]['meas_v']
           i_info[i]=result_i[0]['meas_i']
          # print(result_adc_stdd)
           adc_stdd[i]=result_adc_stdd[0]['adc_stdd']
           adc_mean[i]=result_adc_mean[0]['adc_mean']
       else:
           v_info[i]=[]
           i_info[i]=[]
          # print(result_adc_stdd)
           adc_stdd[i]=[]
           adc_mean[i]=[]
    await conn.close()
    return module_names_array, v_info,i_info,adc_stdd,adc_mean
def root_file_create(ass_date_start,module_names_array,v_info,i_info,adc_stdd,adc_mean):
    myFile = ROOT.TFile.Open(f"summary_since_"+ass_date_start+".root", "RECREATE")
    trees={}
    for i in module_names_array:
        var_i = array('f', [ 0 ])
        var_v = array('f', [ 0 ])
        var_std = array('f', [ 0 ])
        var_mean = array('f', [ 0 ])
        
        trees[i] = ROOT.TTree(f"{i}", f"{i}")
        
        trees[i].Branch("meas_i",var_i,"leafname/F")
        trees[i].Branch("meas_v",var_v,"leafname/F")
        trees[i].Branch("adc_stdd",var_std,"leafname/F")
        trees[i].Branch("adc_mean",var_mean,"leafname/F")
        max_length = max(len(v_info[i]), len(i_info[i]), len(adc_stdd[i]), len(adc_mean[i]))

        try:
            for j in range(max_length+1):
                var_i[0]=i_info[i][j] if j < len(i_info[i]) else 0.0
                var_v[0]=v_info[i][j] if j < len(v_info[i]) else 10000.0
                var_std[0]=adc_stdd[i][j] if j < len(adc_stdd[i]) else 1001.0
                var_mean[0]=adc_mean[i][j] if j < len(adc_mean[i]) else 1001.0
                trees[i].Fill()
            #for k in range(len(adc_stdd[i])):
            #    var_std[0]=adc_stdd[i][k]
            #    var_mean[0]=adc_mean[i][k]
            #    trees[i].Fill()
        except:
            print("error filling tree womp womp")
            var_i[0] = 0.0
            var_v[0] = 10000.0
            var_std[0] = 1001.0
            var_mean[0] = 1001.0
            trees[i].Fill()

        trees[i].Write()

    myFile.Close()
    print("perhaps i made a summary root file?")

def plot_summary(input_root_file,module_names_array,ass_date_start):
    fig, ax = plt.subplots()
    for j in module_names_array:
        f = uproot.open(input_root_file)
        i=f[j+'/meas_i'].array()
        v=f[j+'/meas_v'].array()
        ax.plot(v, i, label=j)
    ax.set_xlim(0, 850)
    ax.set_title('IV Summary of production since ' + ass_date_start)
    ax.set_yscale('log')
    ax.set_xlabel('V')
    ax.set_ylabel('I [A]')
    ax.legend(fontsize='small')
    std=[]
    means=[]
    return fig

def std_summary(input_root_file,module_names_array,ass_date_start):
    #def mean_summary(input_root_file,module_names_array,ass_date_start):
    fig, ax = plt.subplots()
    mean=[]
    std=[]
    for j in module_names_array:
        f = uproot.open(input_root_file)
        mean.append(f[j+'/meas_i'].array())
        #v=f[j+'/meas_v'].array()
    ax.hist(mean)
    ax.set_xlim(0,10)
    ax.set_title('ADC noise - Summary of production since ' + ass_date_start)
    #ax.set_yscale('log')
    ax.set_xlabel('noise_adc')
#    ax.set_ylabel('I [A]')
    ax.legend(fontsize='small')
    plt.show()
    return fig

def mean_summary(input_root_file,module_names_array,ass_date_start):
    fig, ax = plt.subplots()
    mean=[]
    std=[]
    for j in module_names_array:
        f = uproot.open(input_root_file)
        mean.append(f[j+'/meas_i'].array())
        #v=f[j+'/meas_v'].array()
    ax.hist(mean,20)
    ax.set_xlim(0,200)
    ax.set_title('ADC mean - Summary of production since ' + ass_date_start)
    #ax.set_yscale('log')
    ax.set_xlabel('mean_adc')
    #    ax.set_ylabel('I [A]')
    ax.legend(fontsize='small')
    plt.show()
    return fig

    '''plt.figure(figsize=(8, 6))
    plt.hist(std)
    plt.title('Summary ADC STDD since ' +ass_date_start)
    plt.xlabel('ADC STDD')
    plt.ylabel('Count')
    plt.savefig('adc_std_summary_'+ass_date_start+'.pdf')

    plt.figure(figsize=(8, 6))
    plt.hist(means)
    plt.title('Summary ADC mean since ' +ass_date_start)
    plt.xlabel('ADC mean')
    plt.ylabel('Count')
    plt.savefig('adc_mean_summary_'+ass_date_start+'.pdf')
'''

#module_names_array,v_info,i_info,adc_stdd,adc_mean =asyncio.run(fetch_module_info('2025-03-04','mac'))
#print(v_info)
#root_file_create('2025-03-04',module_names_array,v_info,i_info,adc_stdd,adc_mean) 
#plot_summary('summary_since_'+args.date+'.root',module_names_array,args.date)
#mean_summary('summary_since_'+'2025-03-04'+'.root',module_names_array,'2025-03-04')
