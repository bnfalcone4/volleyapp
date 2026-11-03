import streamlit as st
import pandas as pd

import asyncio
from spond import spond

username = 'bnfalcone@yahoo.es'
password = 'Gryphon2010!!'
group_id = '687D3E58108F4A91AC20E3BEF9864E1C'  # test

#st.title('Volleyball Positions')

async def main():
    s = spond.Spond(username=username, password=password)
    group = await s.get_group(group_id)
    #st.title(group['name'])
    
    events = await s.get_events(group_id)

    print(events)

    await s.clientsession.close()

asyncio.run(main())