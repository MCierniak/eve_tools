#TODO
#Function - median (input- values list, qty list), return median value and 4 lists - 50% low values and qty, 50% high values and qty

import numpy as np
import webbrowser
import itertools
import logging
import uuid
import time
import os

from esipy import EsiApp, EsiClient, EsiSecurity
from esipy.exceptions import APIException
from multiprocessing import Process, Queue
from flask import Flask, request

#Global variables
esi_dat = []
if os.path.exists("esi_info.dat"):
    esi_dat = open("esi_info.dat", 'r').read().splitlines()
else:
    raise RuntimeError("esi_info.dat file missing")
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
def esi_init(esi_scopes = [], verbose = True):
    if len(esi_scopes) > 0:
        server = Process(target = server_start)
        server.start()

        if verbose:
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

        if verbose:
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

#ESI system ids from region
def solar_systems_in_region(r_id, esi_api, esi_client, verbose = True):
    if verbose:
        print("Extracting solar system ids in region", r_id, "...")
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

#ESI structure ids from system
def structures_in_system(s_id, esi_api, esi_client, esi_tokens, esi_api_info, verbose = True):
    if verbose:
        print("Extracting structure ids in system", s_id, "...")
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

#ESI market data from structure
def market_in_structure(s_id, esi_api, esi_client, esi_tokens, esi_api_info, verbose = True):
    if verbose:
        print("Collecting market data from structure", s_id, "...")
    if "esi-markets.structure_markets.v1" in esi_api_info["scp"]:
        data = []
        opp = esi_api.op["get_markets_structures_structure_id"](
                page = 1,
                structure_id = s_id,
                token = esi_tokens["access_token"]
        )
        esi_payload = esi_client.request(opp, raise_on_error = True)
        for el in esi_payload.data:
            data.append(el)
        for i in range(2, esi_payload.header["X-Pages"][0] + 1):
            opp2 = esi_api.op["get_markets_structures_structure_id"](
                page = i,
                structure_id = s_id,
                token = esi_tokens["access_token"]
            )
            esi_payload2 = esi_client.request(opp2, raise_on_error = True)
            for el in esi_payload2.data:
                data.append(el)
        return data
    else:
        raise RuntimeError("missing scope - esi-markets.structure_markets.v1")

#ESI list of character assets
def character_assets(esi_api, esi_client, esi_tokens, esi_api_info, verbose = True):
    if verbose:
        print("Collecting asset data of character", esi_api_info["sub"].replace("CHARACTER:EVE:",""), "...")
    if "esi-assets.read_assets.v1" in esi_api_info["scp"]:
        data = []
        opp = esi_api.op["get_characters_character_id_assets"](
                page = 1,
                character_id = esi_api_info["sub"].replace("CHARACTER:EVE:",""),
                token = esi_tokens["access_token"]
        )
        esi_payload = esi_client.request(opp, raise_on_error = True)
        for el in esi_payload.data:
            data.append(el)
        for i in range(2, esi_payload.header["X-Pages"][0] + 1):
            opp2 = esi_api.op["get_characters_character_id_assets"](
                page = i,
                character_id = esi_api_info["sub"].replace("CHARACTER:EVE:",""),
                token = esi_tokens["access_token"]
            )
            esi_payload2 = esi_client.request(opp2, raise_on_error = True)
            for el in esi_payload2.data:
                data.append(el)
        return data
    else:
        raise RuntimeError("missing scope - esi-assets.read_assets.v1")

#incomplete
def pi_factory_profit():

    esi_scopes = ["esi-markets.structure_markets.v1"]
    ids ={
        "1DQ1-A market"                     : 1030049082711,
        "4O-239 market"                     : 1037052098637,
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

    print("Extracting market data...")
    data = []
    temp = market_in_structure(ids["1DQ1-A market"], esi_api, esi_client, esi_tokens, esi_api_info, verbose = False)
    for el in temp:
        data.append(el)
    temp = market_in_structure(ids["4O-239 market"], esi_api, esi_client, esi_tokens, esi_api_info, verbose = False)
    for el in temp:
        data.append(el)

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
        print(el)
        input()
        if el["is_buy_order"]:
            if el["type_id"] in pi_data_buy_value:
                pi_data_buy_value[el["type_id"]].append(el["price"])
                pi_data_buy_qty[el["type_id"]].append(el["volume_remain"])
        else:
            if el["type_id"] in pi_data_sell_value:
                pi_data_sell_value[el["type_id"]].append(el["price"])
                pi_data_sell_qty[el["type_id"]].append(el["volume_remain"])

    print(pi_data_sell_value[ids["Bacteria"]])
    print(pi_data_sell_qty[ids["Bacteria"]])

def reaction_planner():
    print("Reaction planner v1.1")
    ids={
        "Tatara_1dq" : 1029397786276,
        "mats_hangar" : 1038078532852,
        "Atmospheric Gases" : 16634,
        "Cadmium" : 16643,
        "Caesium" : 16647,
        "Chromium" : 16641,
        "Cobalt" : 16640,
        "Dysprosium" : 16650,
        "Evaporite Deposits" : 16635,
        "Hafnium" : 16648,
        "Hydrocarbons" : 16633,
        "Mercury" : 16646,
        "Neodymium" : 16651,
        "Platinum" : 16644,
        "Promethium" : 16652,
        "Scandium" : 16639,
        "Silicates" : 16636,
        "Technetium" : 16649,
        "Thulium" : 16653,
        "Titanium" : 16638,
        "Tungsten" : 16637,
        "Vanadium" : 16642,
        "Caesarium Cadmide" : 16663,
        "Carbon Fiber" : 57453,
        "Carbon Polymers" : 16659,
        "Ceramic Powder" : 16660,
        "Crystallite Alloy" : 16655,
        "Dysporite" : 16668,
        "Fernite Alloy" : 16656,
        "Ferrofluid" : 16669,
        "Fluxed Condensates" : 17769,
        "Hexite" : 16665,
        "Hyperflurite" : 16666,
        "Neo Mercurite" : 16667,
        "Oxy-Organic Solvents" : 57454,
        "Platinum Technite" : 16662,
        "Prometium" : 17960,
        "Promethium Mercurite" : 33337,
        "Rolled Tungsten Alloy" : 16657,
        "Silicon Diborite" : 16658,
        "Solerium" : 16664,
        "Sulfuric Acid" : 16661,
        "Thermosetting Polymer" : 57455,
        "Thulium Hafnite" : 33336,
        "Titanium Chromide" : 16654,
        "Vanadium Hafnite" : 17959
        }
    esi_scopes = ["esi-assets.read_assets.v1"]
    print("Collecting resource data...")
    esi_api, esi_client, esi_tokens, esi_api_info = esi_init(esi_scopes)
    asset_data = character_assets(esi_api, esi_client, esi_tokens, esi_api_info, verbose = True)
    resource_t0 = {
        "Atmospheric Gases"     : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Atmospheric Gases"]]), 0),
        "Cadmium"               : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Cadmium"]]), 0),
        "Caesium"               : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Caesium"]]), 0),
        "Chromium"              : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Chromium"]]), 0),
        "Cobalt"                : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Cobalt"]]), 0),
        "Dysprosium"            : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Dysprosium"]]), 0),
        "Evaporite Deposits"    : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Evaporite Deposits"]]), 0),
        "Hafnium"               : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Hafnium"]]), 0),
        "Hydrocarbons"          : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Hydrocarbons"]]), 0),
        "Mercury"               : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Mercury"]]), 0),
        "Neodymium"             : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Neodymium"]]), 0),
        "Platinum"              : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Platinum"]]), 0),
        "Promethium"            : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Promethium"]]), 0),
        "Scandium"              : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Scandium"]]), 0),
        "Silicates"             : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Silicates"]]), 0),
        "Technetium"            : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Technetium"]]), 0),
        "Thulium"               : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Thulium"]]), 0),
        "Titanium"              : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Titanium"]]), 0),
        "Tungsten"              : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Tungsten"]]), 0),
        "Vanadium"              : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Vanadium"]]), 0)
        }
    resource_t1 = {
        "Caesarium Cadmide"     : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Caesarium Cadmide"]]), 0),
        "Carbon Fiber"          : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Carbon Fiber"]]), 0),
        "Carbon Polymers"       : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Carbon Polymers"]]), 0),
        "Ceramic Powder"        : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Ceramic Powder"]]), 0),
        "Crystallite Alloy"     : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Crystallite Alloy"]]), 0),
        "Dysporite"             : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Dysporite"]]), 0),
        "Fernite Alloy"         : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Fernite Alloy"]]), 0),
        "Ferrofluid"            : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Ferrofluid"]]), 0),
        "Fluxed Condensates"    : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Fluxed Condensates"]]), 0),
        "Hexite"                : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Hexite"]]), 0),
        "Hyperflurite"          : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Hyperflurite"]]), 0),
        "Neo Mercurite"         : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Neo Mercurite"]]), 0),
        "Oxy-Organic Solvents"  : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Oxy-Organic Solvents"]]), 0),
        "Platinum Technite"     : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Platinum Technite"]]), 0),
        "Prometium"             : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Prometium"]]), 0),
        "Promethium Mercurite"  : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Promethium Mercurite"]]), 0),
        "Rolled Tungsten Alloy" : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Rolled Tungsten Alloy"]]), 0),
        "Silicon Diborite"      : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Silicon Diborite"]]), 0),
        "Solerium"              : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Solerium"]]), 0),
        "Sulfuric Acid"         : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Sulfuric Acid"]]), 0),
        "Thermosetting Polymer" : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Thermosetting Polymer"]]), 0),
        "Thulium Hafnite"       : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Thulium Hafnite"]]), 0),
        "Titanium Chromide"     : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Titanium Chromide"]]), 0),
        "Vanadium Hafnite"      : next(iter([el["quantity"] for el in asset_data if el["location_id"] == ids["mats_hangar"] and el["type_id"] == ids["Vanadium Hafnite"]]), 0)
        }
    runs_t1 = {
        "Caesarium Cadmide"     : 0,
        "Carbon Fiber"          : 0,
        "Carbon Polymers"       : 0,
        "Ceramic Powder"        : 0,
        "Crystallite Alloy"     : 0,
        "Dysporite"             : 0,
        "Fernite Alloy"         : 0,
        "Ferrofluid"            : 0,
        "Fluxed Condensates"    : 0,
        "Hexite"                : 0,
        "Hyperflurite"          : 0,
        "Neo Mercurite"         : 0,
        "Oxy-Organic Solvents"  : 0,
        "Platinum Technite"     : 0,
        "Prometium"             : 0,
        "Promethium Mercurite"  : 0,
        "Rolled Tungsten Alloy" : 0,
        "Silicon Diborite"      : 0,
        "Solerium"              : 0,
        "Sulfuric Acid"         : 0,
        "Thermosetting Polymer" : 0,
        "Thulium Hafnite"       : 0,
        "Titanium Chromide"     : 0,
        "Vanadium Hafnite"      : 0
        }
    fuel = {
        "Nitrogen Fuel Block" : 0,
        "Helium Fuel Block" : 0,
        "Oxygen Fuel Block" : 0,
        "Hydrogen Fuel Block" : 0
        }
    runs_t2 = {
        "Reinforced Carbon Fiber" : 0,
        "Pressurized Oxidizers" : 0,
        "Crystalline Carbonide" : 0,
        "Phenolic Composites" : 0,
        "Fernite Carbide" : 0,
        "Titanium Carbide" : 0,
        "Tungsten Carbide" : 0,
        "Sylramic Fibers" : 0,
        "Fulleride" : 0,
        "Terahertz Metamaterials" : 0,
        "Photonic Metamaterials" : 0,
        "Plasmonic Metamaterials" : 0,
        "Nonlinear Metamaterials" : 0,
        "Nanotransistors" : 0,
        "Hypersynaptic Fibers" : 0,
        "Ferrogel" : 0,
        "Fermionic Condensates" : 0
        }
    def react(r_t0, r_t1, o, t1, f):
        temp_r_t0 = {key : r_t0[key] for key in r_t0}
        temp_r_t1 = {key : r_t1[key] for key in r_t1}
        temp_o = {key : o[key] for key in o}
        temp_t1 = {key : t1[key] for key in t1}
        temp_f = {key : f[key] for key in f}
        #0
        for i in range(temp_o["Reinforced Carbon Fiber"]):
            if temp_r_t1["Carbon Fiber"] >= 200:
                temp_r_t1["Carbon Fiber"] -= 200
            else:
                temp_t1["Carbon Fiber"] += 1
                temp_r_t0["Hydrocarbons"] -= 100
                temp_r_t0["Evaporite Deposits"] -= 100
                temp_f["Hydrogen Fuel Block"] += 5
            if temp_r_t1["Thermosetting Polymer"] >= 200:
                temp_r_t1["Thermosetting Polymer"] -= 200
            else:
                temp_t1["Thermosetting Polymer"] += 1
                temp_r_t0["Atmospheric Gases"] -= 100
                temp_r_t0["Silicates"] -= 100
                temp_f["Oxygen Fuel Block"] += 5
            if temp_r_t1["Oxy-Organic Solvents"] >= 1:
                temp_r_t1["Oxy-Organic Solvents"] -= 1
            else:
                temp_t1["Oxy-Organic Solvents"] += 1
                temp_r_t0["Hydrocarbons"] -= 2000
                temp_r_t0["Atmospheric Gases"] -= 2000
                temp_f["Oxygen Fuel Block"] += 5
                temp_r_t1["Oxy-Organic Solvents"] += 9
        #1
        for i in range(temp_o["Pressurized Oxidizers"]):
            if temp_r_t1["Carbon Polymers"] >= 200:
                temp_r_t1["Carbon Polymers"] -= 200
            else:
                temp_t1["Carbon Polymers"] += 1
                temp_r_t0["Hydrocarbons"] -= 100
                temp_r_t0["Silicates"] -= 100
                temp_f["Helium Fuel Block"] += 5
            if temp_r_t1["Sulfuric Acid"] >= 200:
                temp_r_t1["Sulfuric Acid"] -= 200
            else:
                temp_t1["Sulfuric Acid"] += 1
                temp_r_t0["Atmospheric Gases"] -= 100
                temp_r_t0["Evaporite Deposits"] -= 100
                temp_f["Nitrogen Fuel Block"] += 5
            if temp_r_t1["Oxy-Organic Solvents"] >= 1:
                temp_r_t1["Oxy-Organic Solvents"] -= 1
            else:
                temp_t1["Oxy-Organic Solvents"] += 1
                temp_r_t0["Hydrocarbons"] -= 2000
                temp_r_t0["Atmospheric Gases"] -= 2000
                temp_f["Oxygen Fuel Block"] += 5
                temp_r_t1["Oxy-Organic Solvents"] += 9
        #2
        for i in range(temp_o["Crystalline Carbonide"]):
            temp_f["Helium Fuel Block"] += 5
            if temp_r_t1["Carbon Polymers"] >= 100:
                temp_r_t1["Carbon Polymers"] -= 100
            else:
                temp_t1["Carbon Polymers"] += 1
                temp_r_t0["Hydrocarbons"] -= 100
                temp_r_t0["Silicates"] -= 100
                temp_f["Helium Fuel Block"] += 5
                temp_r_t1["Carbon Polymers"] += 100
            if temp_r_t1["Crystallite Alloy"] >= 100:
                temp_r_t1["Crystallite Alloy"] -= 100
            else:
                temp_t1["Crystallite Alloy"] += 1
                temp_r_t0["Cobalt"] -= 100
                temp_r_t0["Cadmium"] -= 100
                temp_f["Helium Fuel Block"] += 5
                temp_r_t1["Crystallite Alloy"] += 100
        #3
        for i in range(temp_o["Phenolic Composites"]):
            temp_f["Oxygen Fuel Block"] += 5
            if temp_r_t1["Silicon Diborite"] >= 100:
                temp_r_t1["Silicon Diborite"] -= 100
            else:
                temp_t1["Silicon Diborite"] += 1
                temp_r_t0["Evaporite Deposits"] -= 100
                temp_r_t0["Silicates"] -= 100
                temp_f["Oxygen Fuel Block"] += 5
                temp_r_t1["Silicon Diborite"] += 100
            if temp_r_t1["Caesarium Cadmide"] >= 100:
                temp_r_t1["Caesarium Cadmide"] -= 100
            else:
                temp_t1["Caesarium Cadmide"] += 1
                temp_r_t0["Cadmium"] -= 100
                temp_r_t0["Caesium"] -= 100
                temp_f["Oxygen Fuel Block"] += 5
                temp_r_t1["Caesarium Cadmide"] += 100
            if temp_r_t1["Vanadium Hafnite"] >= 100:
                temp_r_t1["Vanadium Hafnite"] -= 100
            else:
                temp_t1["Vanadium Hafnite"] += 1
                temp_r_t0["Vanadium"] -= 100
                temp_r_t0["Hafnium"] -= 100
                temp_f["Hydrogen Fuel Block"] += 5
                temp_r_t1["Vanadium Hafnite"] += 100
        #4
        for i in range(temp_o["Fernite Carbide"]):
            temp_f["Hydrogen Fuel Block"] += 5
            if temp_r_t1["Fernite Alloy"] >= 100:
                temp_r_t1["Fernite Alloy"] -= 100
            else:
                temp_t1["Fernite Alloy"] += 1
                temp_r_t0["Scandium"] -= 100
                temp_r_t0["Vanadium"] -= 100
                temp_f["Hydrogen Fuel Block"] += 5
                temp_r_t1["Fernite Alloy"] += 100
            if temp_r_t1["Ceramic Powder"] >= 100:
                temp_r_t1["Ceramic Powder"] -= 100
            else:
                temp_t1["Ceramic Powder"] += 1
                temp_r_t0["Evaporite Deposits"] -= 100
                temp_r_t0["Silicates"] -= 100
                temp_f["Hydrogen Fuel Block"] += 5
                temp_r_t1["Ceramic Powder"] += 100
        #5
        for i in range(temp_o["Titanium Carbide"]):
            temp_f["Oxygen Fuel Block"] += 5
            if temp_r_t1["Titanium Chromide"] >= 100:
                temp_r_t1["Titanium Chromide"] -= 100
            else:
                temp_t1["Titanium Chromide"] += 1
                temp_r_t0["Titanium"] -= 100
                temp_r_t0["Chromium"] -= 100
                temp_f["Oxygen Fuel Block"] += 5
                temp_r_t1["Titanium Chromide"] += 100
            if temp_r_t1["Silicon Diborite"] >= 100:
                temp_r_t1["Silicon Diborite"] -= 100
            else:
                temp_t1["Silicon Diborite"] += 1
                temp_r_t0["Evaporite Deposits"] -= 100
                temp_r_t0["Silicates"] -= 100
                temp_f["Oxygen Fuel Block"] += 5
                temp_r_t1["Silicon Diborite"] += 100
        #6
        for i in range(temp_o["Tungsten Carbide"]):
            temp_f["Nitrogen Fuel Block"] += 5
            if temp_r_t1["Rolled Tungsten Alloy"] >= 100:
                temp_r_t1["Rolled Tungsten Alloy"] -= 100
            else:
                temp_t1["Rolled Tungsten Alloy"] += 1
                temp_r_t0["Tungsten"] -= 100
                temp_r_t0["Platinum"] -= 100
                temp_f["Nitrogen Fuel Block"] += 5
                temp_r_t1["Rolled Tungsten Alloy"] += 100
            if temp_r_t1["Sulfuric Acid"] >= 100:
                temp_r_t1["Sulfuric Acid"] -= 100
            else:
                temp_t1["Sulfuric Acid"] += 1
                temp_r_t0["Atmospheric Gases"] -= 100
                temp_r_t0["Evaporite Deposits"] -= 100
                temp_f["Nitrogen Fuel Block"] += 5
                temp_r_t1["Sulfuric Acid"] += 100
        #7
        for i in range(temp_o["Sylramic Fibers"]):
            temp_f["Helium Fuel Block"] += 5
            if temp_r_t1["Ceramic Powder"] >= 100:
                temp_r_t1["Ceramic Powder"] -= 100
            else:
                temp_t1["Ceramic Powder"] += 1
                temp_r_t0["Evaporite Deposits"] -= 100
                temp_r_t0["Silicates"] -= 100
                temp_f["Hydrogen Fuel Block"] += 5
                temp_r_t1["Ceramic Powder"] += 100
            if temp_r_t1["Hexite"] >= 100:
                temp_r_t1["Hexite"] -= 100
            else:
                temp_t1["Hexite"] += 1
                temp_r_t0["Chromium"] -= 100
                temp_r_t0["Platinum"] -= 100
                temp_f["Nitrogen Fuel Block"] += 5
                temp_r_t1["Hexite"] += 100
        #8
        for i in range(temp_o["Fulleride"]):
            temp_f["Nitrogen Fuel Block"] += 5
            if temp_r_t1["Carbon Polymers"] >= 100:
                temp_r_t1["Carbon Polymers"] -= 100
            else:
                temp_t1["Carbon Polymers"] += 1
                temp_r_t0["Hydrocarbons"] -= 100
                temp_r_t0["Silicates"] -= 100
                temp_f["Helium Fuel Block"] += 5
                temp_r_t1["Carbon Polymers"] += 100
            if temp_r_t1["Platinum Technite"] >= 100:
                temp_r_t1["Platinum Technite"] -= 100
            else:
                temp_t1["Platinum Technite"] += 1
                temp_r_t0["Platinum"] -= 100
                temp_r_t0["Technetium"] -= 100
                temp_f["Nitrogen Fuel Block"] += 5
                temp_r_t1["Platinum Technite"] += 100
        #9
        for i in range(temp_o["Terahertz Metamaterials"]):
            temp_f["Helium Fuel Block"] += 5
            if temp_r_t1["Rolled Tungsten Alloy"] >= 100:
                temp_r_t1["Rolled Tungsten Alloy"] -= 100
            else:
                temp_t1["Rolled Tungsten Alloy"] += 1
                temp_r_t0["Tungsten"] -= 100
                temp_r_t0["Platinum"] -= 100
                temp_f["Nitrogen Fuel Block"] += 5
                temp_r_t1["Rolled Tungsten Alloy"] += 100
            if temp_r_t1["Promethium Mercurite"] >= 100:
                temp_r_t1["Promethium Mercurite"] -= 100
            else:
                temp_t1["Promethium Mercurite"] += 1
                temp_r_t0["Mercury"] -= 100
                temp_r_t0["Promethium"] -= 100
                temp_f["Helium Fuel Block"] += 5
                temp_r_t1["Promethium Mercurite"] += 100
        #10
        for i in range(temp_o["Photonic Metamaterials"]):
            temp_f["Oxygen Fuel Block"] += 5
            if temp_r_t1["Crystallite Alloy"] >= 100:
                temp_r_t1["Crystallite Alloy"] -= 100
            else:
                temp_t1["Crystallite Alloy"] += 1
                temp_r_t0["Cobalt"] -= 100
                temp_r_t0["Cadmium"] -= 100
                temp_f["Helium Fuel Block"] += 5
                temp_r_t1["Crystallite Alloy"] += 100
            if temp_r_t1["Thulium Hafnite"] >= 100:
                temp_r_t1["Thulium Hafnite"] -= 100
            else:
                temp_t1["Thulium Hafnite"] += 1
                temp_r_t0["Hafnium"] -= 100
                temp_r_t0["Thulium"] -= 100
                temp_f["Hydrogen Fuel Block"] += 5
                temp_r_t1["Thulium Hafnite"] += 100
        #11
        for i in range(temp_o["Plasmonic Metamaterials"]):
            temp_f["Hydrogen Fuel Block"] += 5
            if temp_r_t1["Fernite Alloy"] >= 100:
                temp_r_t1["Fernite Alloy"] -= 100
            else:
                temp_t1["Fernite Alloy"] += 1
                temp_r_t0["Scandium"] -= 100
                temp_r_t0["Vanadium"] -= 100
                temp_f["Hydrogen Fuel Block"] += 5
                temp_r_t1["Fernite Alloy"] += 100
            if temp_r_t1["Neo Mercurite"] >= 100:
                temp_r_t1["Neo Mercurite"] -= 100
            else:
                temp_t1["Neo Mercurite"] += 1
                temp_r_t0["Mercury"] -= 100
                temp_r_t0["Neodymium"] -= 100
                temp_f["Helium Fuel Block"] += 5
                temp_r_t1["Neo Mercurite"] += 100
        #12
        for i in range(temp_o["Nonlinear Metamaterials"]):
            temp_f["Nitrogen Fuel Block"] += 5
            if temp_r_t1["Titanium Chromide"] >= 100:
                temp_r_t1["Titanium Chromide"] -= 100
            else:
                temp_t1["Titanium Chromide"] += 1
                temp_r_t0["Titanium"] -= 100
                temp_r_t0["Chromium"] -= 100
                temp_f["Oxygen Fuel Block"] += 5
                temp_r_t1["Titanium Chromide"] += 100
            if temp_r_t1["Ferrofluid"] >= 100:
                temp_r_t1["Ferrofluid"] -= 100
            else:
                temp_t1["Ferrofluid"] += 1
                temp_r_t0["Hafnium"] -= 100
                temp_r_t0["Dysprosium"] -= 100
                temp_f["Hydrogen Fuel Block"] += 5
                temp_r_t1["Ferrofluid"] += 100
        #13
        for i in range(temp_o["Nanotransistors"]):
            temp_f["Nitrogen Fuel Block"] += 5
            if temp_r_t1["Sulfuric Acid"] >= 100:
                temp_r_t1["Sulfuric Acid"] -= 100
            else:
                temp_t1["Sulfuric Acid"] += 1
                temp_r_t0["Atmospheric Gases"] -= 100
                temp_r_t0["Evaporite Deposits"] -= 100
                temp_f["Nitrogen Fuel Block"] += 5
                temp_r_t1["Sulfuric Acid"] += 100
            if temp_r_t1["Platinum Technite"] >= 100:
                temp_r_t1["Platinum Technite"] -= 100
            else:
                temp_t1["Platinum Technite"] += 1
                temp_r_t0["Platinum"] -= 100
                temp_r_t0["Technetium"] -= 100
                temp_f["Nitrogen Fuel Block"] += 5
                temp_r_t1["Platinum Technite"] += 100
            if temp_r_t1["Neo Mercurite"] >= 100:
                temp_r_t1["Neo Mercurite"] -= 100
            else:
                temp_t1["Neo Mercurite"] += 1
                temp_r_t0["Mercury"] -= 100
                temp_r_t0["Neodymium"] -= 100
                temp_f["Helium Fuel Block"] += 5
                temp_r_t1["Neo Mercurite"] += 100
        #14
        for i in range(temp_o["Hypersynaptic Fibers"]):
            temp_f["Oxygen Fuel Block"] += 5
            if temp_r_t1["Solerium"] >= 100:
                temp_r_t1["Solerium"] -= 100
            else:
                temp_t1["Solerium"] += 1
                temp_r_t0["Chromium"] -= 100
                temp_r_t0["Caesium"] -= 100
                temp_f["Oxygen Fuel Block"] += 5
                temp_r_t1["Solerium"] += 100
            if temp_r_t1["Dysporite"] >= 100:
                temp_r_t1["Dysporite"] -= 100
            else:
                temp_t1["Dysporite"] += 1
                temp_r_t0["Mercury"] -= 100
                temp_r_t0["Dysprosium"] -= 100
                temp_f["Helium Fuel Block"] += 5
                temp_r_t1["Dysporite"] += 100
            if temp_r_t1["Vanadium Hafnite"] >= 100:
                temp_r_t1["Vanadium Hafnite"] -= 100
            else:
                temp_t1["Vanadium Hafnite"] += 1
                temp_r_t0["Vanadium"] -= 100
                temp_r_t0["Hafnium"] -= 100
                temp_f["Hydrogen Fuel Block"] += 5
                temp_r_t1["Vanadium Hafnite"] += 100
        #15
        for i in range(temp_o["Ferrogel"]):
            temp_f["Hydrogen Fuel Block"] += 5
            if temp_r_t1["Hexite"] >= 100:
                temp_r_t1["Hexite"] -= 100
            else:
                temp_t1["Hexite"] += 1
                temp_r_t0["Chromium"] -= 100
                temp_r_t0["Platinum"] -= 100
                temp_f["Nitrogen Fuel Block"] += 5
                temp_r_t1["Hexite"] += 100
            if temp_r_t1["Hyperflurite"] >= 100:
                temp_r_t1["Hyperflurite"] -= 100
            else:
                temp_t1["Hyperflurite"] += 1
                temp_r_t0["Vanadium"] -= 100
                temp_r_t0["Promethium"] -= 100
                temp_f["Nitrogen Fuel Block"] += 5
                temp_r_t1["Hyperflurite"] += 100
            if temp_r_t1["Ferrofluid"] >= 100:
                temp_r_t1["Ferrofluid"] -= 100
            else:
                temp_t1["Ferrofluid"] += 1
                temp_r_t0["Hafnium"] -= 100
                temp_r_t0["Dysprosium"] -= 100
                temp_f["Hydrogen Fuel Block"] += 5
                temp_r_t1["Ferrofluid"] += 100
            if temp_r_t1["Prometium"] >= 100:
                temp_r_t1["Prometium"] -= 100
            else:
                temp_t1["Prometium"] += 1
                temp_r_t0["Cadmium"] -= 100
                temp_r_t0["Promethium"] -= 100
                temp_f["Oxygen Fuel Block"] += 5
                temp_r_t1["Prometium"] += 100
        #16
        for i in range(temp_o["Fermionic Condensates"]):
            temp_f["Helium Fuel Block"] += 5
            if temp_r_t1["Caesarium Cadmide"] >= 100:
                temp_r_t1["Caesarium Cadmide"] -= 100
            else:
                temp_t1["Caesarium Cadmide"] += 1
                temp_r_t0["Cadmium"] -= 100
                temp_r_t0["Caesium"] -= 100
                temp_f["Oxygen Fuel Block"] += 5
                temp_r_t1["Caesarium Cadmide"] += 100
            if temp_r_t1["Dysporite"] >= 100:
                temp_r_t1["Dysporite"] -= 100
            else:
                temp_t1["Dysporite"] += 1
                temp_r_t0["Mercury"] -= 100
                temp_r_t0["Dysprosium"] -= 100
                temp_f["Helium Fuel Block"] += 5
                temp_r_t1["Dysporite"] += 100
            if temp_r_t1["Fluxed Condensates"] >= 100:
                temp_r_t1["Fluxed Condensates"] -= 100
            else:
                temp_t1["Fluxed Condensates"] += 1
                temp_r_t0["Neodymium"] -= 100
                temp_r_t0["Thulium"] -= 100
                temp_f["Oxygen Fuel Block"] += 5
                temp_r_t1["Fluxed Condensates"] += 100
            if temp_r_t1["Prometium"] >= 100:
                temp_r_t1["Prometium"] -= 100
            else:
                temp_t1["Prometium"] += 1
                temp_r_t0["Cadmium"] -= 100
                temp_r_t0["Promethium"] -= 100
                temp_f["Oxygen Fuel Block"] += 5
                temp_r_t1["Prometium"] += 100
        return temp_r_t0, temp_r_t1, temp_o, temp_t1, temp_f
    
    best_o = {}
    best_resource = 1e300
    best_fuel = {key : fuel[key] for key in fuel}
    best_runs_t2 = {key : runs_t2[key] for key in runs_t2}
    best_runs_t1 = {key : runs_t1[key] for key in runs_t1}
    best_resource_t0 = {key : resource_t0[key] for key in resource_t0}
    best_resource_t1 = {key : resource_t1[key] for key in resource_t1}
    best_combination = 0
    print("Calculating reaction plans...")
    combination = [
        (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16)
        ]
    #for j, subset in enumerate(itertools.permutations([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16])):
    for j, subset in enumerate(combination):
        per = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        for i in list(subset):
            while True:
                per[i] += 1
                temp_runs_t2 = {key : runs_t2[key] for key in runs_t2}
                temp_runs_t2["Reinforced Carbon Fiber"] = per[0]
                temp_runs_t2["Pressurized Oxidizers"] = per[1]
                temp_runs_t2["Crystalline Carbonide"] = per[2]
                temp_runs_t2["Phenolic Composites"] = per[3]
                temp_runs_t2["Fernite Carbide"] = per[4]
                temp_runs_t2["Titanium Carbide"] = per[5]
                temp_runs_t2["Tungsten Carbide"] = per[6]
                temp_runs_t2["Sylramic Fibers"] = per[7]
                temp_runs_t2["Fulleride"] = per[8]
                temp_runs_t2["Terahertz Metamaterials"] = per[9]
                temp_runs_t2["Photonic Metamaterials"] = per[10]
                temp_runs_t2["Plasmonic Metamaterials"] = per[11]
                temp_runs_t2["Nonlinear Metamaterials"] = per[12]
                temp_runs_t2["Nanotransistors"] = per[13]
                temp_runs_t2["Hypersynaptic Fibers"] = per[14]
                temp_runs_t2["Ferrogel"] = per[15]
                temp_runs_t2["Fermionic Condensates"] = per[16]
                temp_resource_t0 = {key : resource_t0[key] for key in resource_t0}
                temp_resource_t1 = {key : resource_t1[key] for key in resource_t1}
                temp_runs_t1 = {key : runs_t1[key] for key in runs_t1}
                temp_fuel = {key : fuel[key] for key in fuel}
                temp_resource_t0, temp_resource_t1, temp_runs_t2, temp_runs_t1, temp_fuel = react(temp_resource_t0, temp_resource_t1, temp_runs_t2, temp_runs_t1, temp_fuel)
                if np.all([(el>=0) for el in temp_resource_t0.values()]) and np.all([(el>=0) for el in temp_resource_t1.values()]):
                    if sum(temp_resource_t0.values()) + sum(temp_resource_t1.values()) <= best_resource:
                        best_combination = j
                        best_resource = sum(temp_resource_t0.values()) + sum(temp_resource_t1.values())
                        best_runs_t2 = {key : temp_runs_t2[key] for key in temp_runs_t2}
                        best_runs_t1 = {key : temp_runs_t1[key] for key in temp_runs_t1}
                        best_resource_t0 = {key : temp_resource_t0[key] for key in temp_resource_t0}
                        best_resource_t1 = {key : temp_resource_t1[key] for key in temp_resource_t1}
                        best_fuel = {key : temp_fuel[key] for key in temp_fuel}
                    continue
                else:
                    per[i] -= 1
                    break

    if(best_resource_t0 == resource_t0):
        print("Calculation failed, insufficient resources!")
    else:
        print("Calculation completed, optimal plan:")
        print("Permutation", best_combination)
        print("T1 job schedule")
        print(best_runs_t1)
        print("T2 job schedule")
        print(best_runs_t2)
        print("Fuel to buy")
        print(best_fuel)
        print("T0 resource left")
        print(best_resource_t0)
        print("T1 resource left")
        print(best_resource_t1)

if __name__ == "__main__":
    #####
    pi_factory_profit()
    #####
    #reaction_planner()