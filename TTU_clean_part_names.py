import asyncpg
import asyncio


### change this
old_new_pair = [
    ['320MLF3W2CM0011', '320MLF2W2CM0011'],
    ['320MLF3T2CM0103', '320MLF3TCCM0104'],
]

async def get_conn():
    conn = await asyncpg.connect(user='editor', 
        password='hgcal',  #### change to editor password
        database='hgcdb',  #### change these 
        host='localhost'   #### change these
        )
    return conn

async def update_part_name(old_part_name, new_part_name, conn, update_sensor_thickness = False):
    column_name = {'320M': 'module_name', '320P': 'proto_name'}[new_part_name[0:4]]
    sensor_thickness = {'1': 100, '2': 200, '3': 300}[new_part_name[6]]

    tables = await conn.fetch(f"""SELECT table_name FROM information_schema.columns WHERE column_name = '{column_name}' AND table_schema = 'public'""")

    for record in tables:
        table_name = record['table_name']
        update_query = f"""UPDATE {table_name} SET {column_name} = '{new_part_name}' WHERE {column_name} = '{old_part_name}'"""
        await conn.execute(update_query)

    if update_sensor_thickness and column_name == 'module_name':
        update_sen_query = f"""UPDATE module_info SET sen_thickness = '{sensor_thickness}' WHERE module_name = '{new_part_name}'"""
        await conn.execute(update_sen_query)

    print(f"{old_part_name} -> {new_part_name}", f"Updated tables: {[record['table_name'] for record in tables]}")


async def main(update_proto = True):
    try:
        conn = await get_conn()
        for i in old_new_pair:
            old_part_name, new_part_name = i[0], i[1]
            await update_part_name(old_part_name, new_part_name, conn=conn, update_sensor_thickness = True)
        
        if update_proto:
            for i in old_new_pair:
                old_part_name, new_part_name = i[0].replace('320M', '320P'), i[1].replace('320M', '320P')
                await update_part_name(old_part_name, new_part_name, conn=conn)

        print("Update completed.")
    finally:
        await conn.close()

asyncio.run(main())
