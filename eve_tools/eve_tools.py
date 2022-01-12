#TODO
#Function - market data from structure; code exists in func pi_factory_profit() (input - structure id, esi interface with scope esi-markets.structure_markets.v1)
#Function - median (input- values list, qty list), return median value and 4 lists - 50% low values and qty, 50% high values and qty
#Function - quartyl_low (input- values list, qty list)
#Function - quartyl_high (input- values list, qty list)

import webbrowser
import logging
import uuid
import time
import os

from esipy import EsiApp, EsiClient, EsiSecurity
from multiprocessing import Process, Queue
from flask import Flask, request

#Global variables
esi_dat = []
if os.path.exists("esi_info"):
    esi_dat = open("esi_info", 'r').read().splitlines()
else:
    raise RuntimeError("esi_info file missing")
esi_client_id = esi_dat[0]
esi_secret_key = esi_dat[1]
esi_redirect_url = esi_dat[2]
esi_headers = {"User-Agent": esi_dat[3]}
esi_state = uuid.uuid4().hex

#Flask interface
app = Flask(__name__)
log = logging.getLogger('werkzeug')
log.disabled = True

@app.route('/callback/')
def get_code():
    esi_token = request.args.get('code')
    if esi_token is not None:
        with open("token", 'w') as file:
            file.write(esi_token)
        return """ 
        <!DOCTYPE html>
        <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <meta http-equiv="X-UA-Compatible" content="ie=edge">
                <title>ESI retriever</title>
            </head>
            <body>
                ESI token retrieved...
            </body>
        </html>
        """
    else:
        return """ 
        <!DOCTYPE html>
        <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <meta http-equiv="X-UA-Compatible" content="ie=edge">
                <title>ESI retriever</title>
            </head>
            <body>
                ESI token not found...
            </body>
        </html>
        """

def server_start():
    os.environ['WERKZEUG_RUN_MAIN'] = 'true'
    app.run(host = "localhost", port = 65432, debug = False)

#ESI initialization and scope authentication
def esi_init(esi_scopes = []):
    if len(esi_scopes) > 0:
        server = Process(target = server_start)
        server.start()

        print("Authenticating...")
        security = EsiSecurity(
            redirect_uri = esi_redirect_url,
            client_id = esi_client_id,
            secret_key = esi_secret_key,
            headers = esi_headers,
        )
        security_url = security.get_auth_uri(
            state = esi_state, 
            scopes = esi_scopes
        )
        webbrowser.open(security_url)

        print("Loading ESI Swagger interface...")
        esi_token = "0"
        esi_swagger = EsiApp().get_latest_swagger
        client = EsiClient(
            retry_requests = True,
            headers = esi_headers,
            raw_body_only = False,
        )
        while esi_token == "0":
            if os.path.exists("token"):
                esi_token = open("token", 'r').read()
                break
            time.sleep(1)
        server.terminate()
        server.join()
        os.remove("token")

        tokens = security.auth(esi_token)
        api_info = security.verify()

        return esi_swagger, client, tokens, api_info
    else:
        print("Loading ESI Swagger interface...")
        esi_swagger = EsiApp().get_latest_swagger
        client = EsiClient(
            retry_requests = True,
            headers = esi_headers,
            raw_body_only = False,
        )

        return esi_swagger, client

#ESI extract all system ids in a region
def solar_systems_in_region(r_id, esi_api, esi_client):
    sys = []
    opp = esi_api.op["get_universe_regions_region_id"](
        region_id = r_id
    )
    esi_payload = esi_client.request(opp, raise_on_error = True)
    for el in esi_payload.data["constellations"]:
        opp2 = esi_api.op["get_universe_constellations_constellation_id"](
            constellation_id = el
        )
        esi_payload2 = esi_client.request(opp2, raise_on_error = True)
        for el2 in esi_payload2.data["systems"]:
            sys.append(el2)
    return sys

#ESI extract all structure ids in a system
def structures_in_system(s_id, esi_api, esi_client, esi_tokens, esi_api_info):
    if "esi-search.search_structures.v1" in esi_api_info["scp"]:
        structures = []
        opp = esi_api.op["get_universe_systems_system_id"](
            system_id = s_id
        )
        esi_payload = esi_client.request(opp, raise_on_error = True)
        opp2 = esi_api.op["get_characters_character_id_search"](
            categories = "structure",
            character_id = esi_api_info["sub"].replace("CHARACTER:EVE:",""),
            search = esi_payload.data["name"],
            token = esi_tokens["access_token"]
        )
        esi_payload2 = esi_client.request(opp2, raise_on_error = True)
        for el in esi_payload2.data["structure"]:
            structures.append(el)
        return structures
    else:
        raise RuntimeError("missing scope - esi-search.search_structures.v1")

def pi_factory_profit():

    esi_scopes = ["esi-markets.structure_markets.v1", "esi-search.search_structures.v1"]
    ids ={
        "Delve"                             : 10000060,
        "Imperial Palace"                   : 1030049082711,
        "Bacteria"                          : 2393,
        "Biofuels"                          : 2396,
        "Biomass"                           : 3779,
        "Chiral Structures"                 : 2401,
        "Electrolytes"                      : 2390,
        "Industrial Fibers"                 : 2397,
        "Oxidizing Compound"                : 2392,
        "Oxygen"                            : 3683,
        "Plasmoids"                         : 2389,
        "Precious Metals"                   : 2399,
        "Proteins"                          : 2395,
        "Reactive Metals"                   : 2398,
        "Silicon"                           : 9828,
        "Toxic Metals"                      : 2400,
        "Water"                             : 3645,
        "Biocells"                          : 2329,
        "Construction Blocks"               : 3828,
        "Consumer Electronics"              : 9836,
        "Coolant"                           : 9832,
        "Enriched Uranium"                  : 44,
        "Fertilizer"                        : 3693,
        "Genetically Enhanced Livestock"    : 15317,
        "Livestock"                         : 3725,
        "Mechanical Parts"                  : 3689,
        "Microfiber Shielding"              : 2327,
        "Miniature Electronics"             : 9842,
        "Nanites"                           : 2463,
        "Oxides"                            : 2317,
        "Polyaramids"                       : 2321,
        "Polytextiles"                      : 3695,
        "Rocket Fuel"                       : 9830,
        "Silicate Glass"                    : 3697,
        "Superconductors"                   : 9838,
        "Supertensile Plastics"             : 2312,
        "Synthetic Oil"                     : 3691,
        "Test Cultures"                     : 2319,
        "Transmitter"                       : 9840,
        "Viral Agent"                       : 3775,
        "Water-Cooled CPU"                  : 2328,
        "Biotech Research Reports"          : 2358,
        "Camera Drones"                     : 2345,
        "Condensates"                       : 2344,
        "Cryoprotectant Solution"           : 2367,
        "Data Chips"                        : 17392,
        "Gel-Matrix Biopaste"               : 2348,
        "Guidance Systems"                  : 9834,
        "Hazmat Detection Systems"          : 2366,
        "Hermetic Membranes"                : 2361,
        "High-Tech Transmitters"            : 17898,
        "Industrial Explosives"             : 2360,
        "Neocoms"                           : 2354,
        "Nuclear Reactors"                  : 2352,
        "Planetary Vehicles"                : 9846,
        "Robotics"                          : 9848,
        "Smartfab Units"                    : 2351,
        "Supercomputers"                    : 2349,
        "Synthetic Synapses"                : 2346,
        "Transcranial Microcontrollers"     : 12836,
        "Ukomi Superconductors"             : 17136,
        "Vaccines"                          : 28974,
        "Broadcast Node"                    : 2867,
        "Integrity Response Drones"         : 2868,
        "Nano-Factory"                      : 2869,
        "Organic Mortar Applicators"        : 2870,
        "Recursive Computing Module"        : 2871,
        "Self-Harmonizing Power Core"       : 2872,
        "Sterile Conduits"                  : 2875,
        "Wetware Mainframe"                 : 2876
    }

    esi_api, esi_client, esi_tokens, esi_api_info = esi_init(esi_scopes)
    
    print("Collecting market data...")
    data = []
    page_nr = 1
    while True:
        opp = esi_api.op["get_markets_structures_structure_id"](
            page = page_nr,
            structure_id = ids["Imperial Palace"],
            token = esi_tokens["access_token"]
        )
        try:
            esi_payload = esi_client.request(opp, raise_on_error = True)
        except:
            break
        for el in esi_payload.data:
            data.append(el)
        page_nr = page_nr + 1

    print("Parsing market data...")
    pi_data_sell_value = {
        2393 : [], 2396 : [], 3779 : [], 2401 : [], 2390 : [], 2397 : [], 2392 : [], 3683 : [], 2389 : [], 2399 : [], 2395 : [], 2398 : [], 9828 : [],
        2400 : [], 3645 : [], 2329 : [], 3828 : [], 9836 : [], 9832 : [], 44 : [], 3693 : [], 15317 : [], 3725 : [], 3689 : [], 2327 : [], 9842 : [],
        2463 : [], 2317 : [], 2321 : [], 3695 : [], 9830 : [], 3697 : [], 9838 : [], 2312 : [], 3691 : [], 2319 : [], 9840 : [], 3775 : [], 2328 : [],
        2358 : [], 2345 : [], 2344 : [], 2367 : [], 17392 : [], 2348 : [], 9834 : [], 2366 : [], 2361 : [], 17898 : [], 2360 : [], 2354 : [], 2352 : [],
        9846 : [], 9848 : [], 2351 : [], 2349 : [], 2346 : [], 12836 : [], 17136 : [], 28974 : [], 2867 : [], 2868 : [], 2869 : [], 2870 : [], 2871 : [],
        2872 : [], 2875 : [], 2876 : []
    }
    pi_data_buy_value = {
        2393 : [], 2396 : [], 3779 : [], 2401 : [], 2390 : [], 2397 : [], 2392 : [], 3683 : [], 2389 : [], 2399 : [], 2395 : [], 2398 : [], 9828 : [],
        2400 : [], 3645 : [], 2329 : [], 3828 : [], 9836 : [], 9832 : [], 44 : [], 3693 : [], 15317 : [], 3725 : [], 3689 : [], 2327 : [], 9842 : [],
        2463 : [], 2317 : [], 2321 : [], 3695 : [], 9830 : [], 3697 : [], 9838 : [], 2312 : [], 3691 : [], 2319 : [], 9840 : [], 3775 : [], 2328 : [],
        2358 : [], 2345 : [], 2344 : [], 2367 : [], 17392 : [], 2348 : [], 9834 : [], 2366 : [], 2361 : [], 17898 : [], 2360 : [], 2354 : [], 2352 : [],
        9846 : [], 9848 : [], 2351 : [], 2349 : [], 2346 : [], 12836 : [], 17136 : [], 28974 : [], 2867 : [], 2868 : [], 2869 : [], 2870 : [], 2871 : [],
        2872 : [], 2875 : [], 2876 : []
    }
    pi_data_sell_qty = {
        2393 : [], 2396 : [], 3779 : [], 2401 : [], 2390 : [], 2397 : [], 2392 : [], 3683 : [], 2389 : [], 2399 : [], 2395 : [], 2398 : [], 9828 : [],
        2400 : [], 3645 : [], 2329 : [], 3828 : [], 9836 : [], 9832 : [], 44 : [], 3693 : [], 15317 : [], 3725 : [], 3689 : [], 2327 : [], 9842 : [],
        2463 : [], 2317 : [], 2321 : [], 3695 : [], 9830 : [], 3697 : [], 9838 : [], 2312 : [], 3691 : [], 2319 : [], 9840 : [], 3775 : [], 2328 : [],
        2358 : [], 2345 : [], 2344 : [], 2367 : [], 17392 : [], 2348 : [], 9834 : [], 2366 : [], 2361 : [], 17898 : [], 2360 : [], 2354 : [], 2352 : [],
        9846 : [], 9848 : [], 2351 : [], 2349 : [], 2346 : [], 12836 : [], 17136 : [], 28974 : [], 2867 : [], 2868 : [], 2869 : [], 2870 : [], 2871 : [],
        2872 : [], 2875 : [], 2876 : []
    }
    pi_data_buy_qty = {
        2393 : [], 2396 : [], 3779 : [], 2401 : [], 2390 : [], 2397 : [], 2392 : [], 3683 : [], 2389 : [], 2399 : [], 2395 : [], 2398 : [], 9828 : [],
        2400 : [], 3645 : [], 2329 : [], 3828 : [], 9836 : [], 9832 : [], 44 : [], 3693 : [], 15317 : [], 3725 : [], 3689 : [], 2327 : [], 9842 : [],
        2463 : [], 2317 : [], 2321 : [], 3695 : [], 9830 : [], 3697 : [], 9838 : [], 2312 : [], 3691 : [], 2319 : [], 9840 : [], 3775 : [], 2328 : [],
        2358 : [], 2345 : [], 2344 : [], 2367 : [], 17392 : [], 2348 : [], 9834 : [], 2366 : [], 2361 : [], 17898 : [], 2360 : [], 2354 : [], 2352 : [],
        9846 : [], 9848 : [], 2351 : [], 2349 : [], 2346 : [], 12836 : [], 17136 : [], 28974 : [], 2867 : [], 2868 : [], 2869 : [], 2870 : [], 2871 : [],
        2872 : [], 2875 : [], 2876 : []
    }
    for el in data:
        if el["is_buy_order"]:
            if el["type_id"] in pi_data_buy_value:
                pi_data_buy_value[el["type_id"]].append(el["price"])
                pi_data_buy_qty[el["type_id"]].append(el["volume_total"])
        else:
            if el["type_id"] in pi_data_sell_value:
                pi_data_sell_value[el["type_id"]].append(el["price"])
                pi_data_sell_qty[el["type_id"]].append(el["volume_total"])

    print(pi_data_buy_value[ids["Bacteria"]])
    print(pi_data_buy_qty[ids["Bacteria"]])

if __name__ == "__main__":
    #####
    #pi_factory_profit()
    esi_scopes = ["esi-markets.structure_markets.v1", "esi-search.search_structures.v1"]
    esi_api, esi_client, esi_tokens, esi_api_info = esi_init(esi_scopes)
    solar_systems = solar_systems_in_region("10000060", esi_api, esi_client)
    structures = []
    for el in solar_systems:
        temp = structures_in_system(el, esi_api, esi_client, esi_tokens, esi_api_info)
        for el2 in temp:
            structures.append(el2)
    print(structures)