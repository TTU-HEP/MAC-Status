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
parser = argparse.ArgumentParser(description="Easy input of date.")

from fastapi import FastAPI
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request
app = FastAPI()

templates = Jinja2Templates(directory="templates")

#parser.add_argument('date', type=str, help="date string")
#parser.add_argument('--viewer_pwd', type=str, default='XXXXX', required=False, help="Viewer PSQL password")
#args = parser.parse_args()
configuration = {}
with open('dbase_info/conn.yaml', 'r') as file:
    configuration = yaml.safe_load(file)

async def inventory_tracker(ass_date_start):
    conn = await asyncpg.connect(
            host = configuration['db_hostname'],
            database = configuration['dbname'],
            user = 'viewer', #configuration['postg']
            password = 'XXXX' #configuration['DBPassword']
        )
    ass_date = datetime.strptime(ass_date_start, '%Y-%m-%d').date()
    module_counting=f"""SELECT COUNT(*) from module_info WHERE assembled >= $1 ;"""
    module_count=await conn.fetch(module_counting,ass_date)
    print("number of modules assembled since start of v3b: ",module_count[0]['count'])

    hxb_counting=f"""SELECT COUNT(*) from hexaboard WHERE module_no >= 1;"""
    hxb_sum=await conn.fetch("""SELECT COUNT(*) from hexaboard;""")
    hxb_total=hxb_sum[0]['count'] - 12
    hxb_count=await conn.fetch(hxb_counting)
    print("number of hxb used since start of v3b: ",hxb_count[0]['count'])

    proto_counting=f"""SELECT COUNT(*) from proto_assembly WHERE ass_run_date >= $1 ;"""
    proto_count=await conn.fetch(proto_counting,ass_date)
    print("number of protomodules assembled since start of v3b: ",proto_count[0]['count'])

    bp_counting=f"""SELECT COUNT(*) from baseplate WHERE proto_no > 12 ;"""
    bp_count=await conn.fetch(bp_counting)
    bp_sum=await conn.fetch("""SELECT COUNT(*) from baseplate;""")
    bp_total=bp_sum[0]['count'] - 12
    print("number of baseplates used since start of v3b: ",bp_count[0]['count'])

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
        "sensor usage": f"{sens_count[0]['count']} of {sens_total}"

    }]
@app.get("/", response_class=HTMLResponse)
async def serve_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/inventory")
async def inventory():
    inventory_data = await inventory_tracker("2025-03-04")  # Call your function
    return JSONResponse(content=inventory_data)
   
