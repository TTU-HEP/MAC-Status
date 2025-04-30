import asyncpg
import asyncio
import yaml
import ROOT
from datetime import datetime
from array import array
import uproot
import matplotlib.pyplot as plt
import argparse
import numpy as np
from summary_maker import *
parser = argparse.ArgumentParser(description="Easy input of date.")

from fastapi import FastAPI
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request
app = FastAPI()

templates = Jinja2Templates(directory="templates")

parser.add_argument('date', type=str, help="date string")
parser.add_argument('--viewer_pwd', type=str, default='XXXXX', required=False, help="Viewer PSQL password")
args = parser.parse_args()
configuration = {}
with open('dbase_info/conn.yaml', 'r') as file:
    configuration = yaml.safe_load(file)

async def inventory_tracker(ass_date_start):
    conn = await asyncpg.connect(
            host = configuration['db_hostname'],
            database = configuration['dbname'],
            user = 'viewer', #configuration['postg']
            password = 'mac' #configuration['DBPassword']
        )
    ass_date = datetime.strptime(ass_date_start, '%Y-%m-%d').date()
    module_counting=f"""SELECT COUNT(*) from module_info WHERE assembled >= $1 ;"""
    module_count=await conn.fetch(module_counting,ass_date)
    print("number of modules assembled since start of v3b: ",module_count[0]['count'])

    hxb_counting=f"""SELECT COUNT(*) from hexaboard WHERE module_no >= 1 AND roc_version != 'V3' ;"""
    hxb_sum=await conn.fetch("""SELECT COUNT(*) from hexaboard;""")
    hxb_total=hxb_sum[0]['count'] - 12
    hxb_count=await conn.fetch(hxb_counting)
    print("number of hxb used since start of v3b: ",hxb_count[0]['count'])

    v3c_counting=f"""SELECT COUNT(*) from hexaboard WHERE module_no >= 1 AND roc_version = 'HGCROCV3c' ;"""
    v3c_sum=await conn.fetch("""SELECT COUNT(*) from hexaboard WHERE roc_version = 'HGCROCV3c';""")
    v3c_total=v3c_sum[0]['count']
    v3c_count=await conn.fetch(v3c_counting)
    print("number of v3c used since start of v3b: ",v3c_count[0]['count'])

    v3b_counting=f"""SELECT COUNT(*) from hexaboard WHERE module_no >= 1 AND roc_version = 'HGCROCV3b-2' ;"""
    v3b_sum=await conn.fetch("""SELECT COUNT(*) from hexaboard;""")
    v3b_total=v3c_sum[0]['count']
    v3b_count=await conn.fetch(v3b_counting)
    print("number of v3b used since start of v3b: ",v3b_count[0]['count'])

    proto_counting=f"""SELECT COUNT(*) from proto_assembly WHERE ass_run_date >= $1 ;"""
    proto_count=await conn.fetch(proto_counting,ass_date)
    print("number of protomodules assembled since start of v3b: ",proto_count[0]['count'])

    bp_counting=f"""SELECT COUNT(*) from baseplate WHERE proto_no > 12 ;"""
    bp_count=await conn.fetch(bp_counting)
    bp_sum=await conn.fetch("""SELECT COUNT(*) from baseplate;""")
    bp_total=bp_sum[0]['count'] - 12
    print("number of baseplates used since start of v3b: ",bp_count[0]['count'])

    cuw_counting=f"""SELECT COUNT(*) from baseplate WHERE proto_no > 12 AND bp_material = 'CuW';"""
    cuw_count=await conn.fetch(cuw_counting)
    cuw_sum=await conn.fetch("""SELECT COUNT(*) from baseplate WHERE bp_material = 'CuW';""")
    cuw_total=cuw_sum[0]['count']
    print("number of cuw used since start of v3b: ",cuw_count[0]['count'])

    ti_counting=f"""SELECT COUNT(*) from baseplate WHERE proto_no > 12 AND bp_material = 'Ti';"""
    ti_count=await conn.fetch(ti_counting)
    ti_sum=await conn.fetch("""SELECT COUNT(*) from baseplate WHERE bp_material = 'Ti';""")
    ti_total=ti_sum[0]['count']
    print("number of ti used since start of v3b: ",ti_count[0]['count'])

    sens_counting=f"""SELECT COUNT(*) from sensor WHERE proto_no > 12 ;"""
    sens_count=await conn.fetch(sens_counting)
    sens_sum=await conn.fetch("""SELECT COUNT(*) from sensor;""")
    sens_total=sens_sum[0]['count'] - 12
    print("number of sensors used since start of v3b: ",sens_count[0]['count'])
    
    return [ {
        "module count": module_count[0]['count'],
        "protomodule count": proto_count[0]['count'],
        "hexaboard usage": f"{hxb_count[0]['count']} of {hxb_total}",
        "baseplate usage": f"{bp_count[0]['count']} of {bp_total}",
        "sensor usage": f"{sens_count[0]['count']} of {sens_total}",
        "v3c": f"{v3c_count[0]['count']} of {v3c_total}",
        "v3b": f"{v3b_count[0]['count']} of {v3b_total}",
        "CuW": f"{cuw_count[0]['count']} of {cuw_total}",
        "Ti": f"{ti_count[0]['count']} of {ti_total}",

    }]

@app.get("/", response_class=HTMLResponse)
async def serve_page(request: Request, ass_date: str = Query("2025-03-04")):
    ass_date = datetime.strptime(ass_date_start, '%Y-%m-%d').date()
    module_names_array,v_info,i_info,adc_stdd,adc_mean =await fetch_module_info(ass_date,'mac')
    root_file_create(ass_date,module_names_array,v_info,i_info,adc_stdd,adc_mean) 
    fig=plot_summary('summary_since_'+ass_date+'.root',module_names_array,ass_date)


    # Convert to base64
    buf = io.BytesIO()
    fig.savefig(buf, format='png')
    buf.seek(0)
    image_base64 = base64.b64encode(buf.read()).decode('utf-8')

    return templates.TemplateResponse("index.html", {
        "request": request,
        "image_url": "/get_plot_image?assemb_date=" + str(assemb_date)
    })
@app.get("/get_plot_image")
async def get_plot_image(assemb_date: str = Query(...)):
    assemb_date = datetime.strptime(assemb_date, '%Y-%m-%d').date()

    # Fetch data and generate the plot when the button is clicked or the image is requested
    module_names_array, v_info, i_info, adc_stdd, adc_mean = await fetch_module_info(assemb_date, 'mac')
    root_file_create(assemb_date, module_names_array, v_info, i_info, adc_stdd, adc_mean)
    fig = plot_summary(f'summary_since_{assemb_date}.root', module_names_array, assemb_date)

    # Convert plot to a BytesIO buffer for streaming
    buf = io.BytesIO()
    fig.savefig(buf, format='png')
    buf.seek(0)

    # Stream the image directly as PNG
    return StreamingResponse(buf, media_type="image/png")


#@app.get("/", response_class=HTMLResponse)
#'''async def serve_page(request: Request):
#    return templates.TemplateResponse("index.html", {"request": request})'''

@app.get("/inventory")
async def inventory():
    inventory_data = await inventory_tracker("2025-03-04")  # Call your function
    return JSONResponse(content=inventory_data)
   
