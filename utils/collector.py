import os

import pandas as pd
from datetime import datetime as dt

from rockyclickup.wrapper import Session as cu
from rockyclickup.utils import response_to_dataframe as clickup_response_to_dataframe
from rockyclickup.models import Client

from rockyelevate.wrapper import Session
from rockyelevate.utils import response_to_dataframe

from utils.clickup import fix_clickup_date
from constants.maps import (
    ORGANIZATION_RENAME_MAP,
    ELEVATE_PLAN_RENAME_MAP,
    CLIENT_RENAME_MAP,
    CLICKUP_PLAN_RENAME_MAP,
    COLS_TO_DROP,
)

clickup = cu()

elevate_server = "PROD"
elv = Session(elevate_server, multithread=True, max_threads=200)

print(elv.max_threads)

today = dt.now()

current_dir = os.getcwd()
parent_dir = os.path.dirname(f"{"\\".join(current_dir.split("\\"))}")
cache_path = rf"..\..\cache"


def get_all_elv_organizations():
    ''' Get all Elevate Organizations ''' # ~11m
    try:
        all_orgs_df = pd.read_pickle(f"{cache_path}/{dt.strftime(today, "%y%m%d")}_ALL_ORGS_{elevate_server}.pkl")
        print(f"opened {len(all_orgs_df)} organizations")

    except FileNotFoundError:
        
        print(f"fetching organizations from elevate, please wait...")
        all_orgs_res = elv.get_organizations(
            statuses=["PENDING", "ACTIVE", "TERMINATED", "ACTIVATION_FAILED"],
            details=["STATUS"],
            types=["SYSTEM", "PARTNER", "DISTRIBUTOR", "COMPANY", "SUBSIDIARY", "SUBGROUP"],
            subsidiaries="include"
        )
        all_orgs_df = response_to_dataframe(all_orgs_res)
        all_orgs_df = all_orgs_df.rename(columns=ORGANIZATION_RENAME_MAP).drop(columns=COLS_TO_DROP, errors='ignore')
        all_orgs_df.to_pickle(f"{cache_path}/{dt.strftime(today, "%y%m%d")}_ALL_ORGS_{elevate_server}.pkl")

        print(f"found {len(all_orgs_df)} organizations")

    return all_orgs_df


def get_all_elv_plans(oids: list = None):
    ''' Get all Elevate Plans ''' # ~2m
    elv_plans_cache_path = f"{cache_path}/{dt.strftime(today, "%y%m%d")}_ALL_PLANS_{elevate_server}.pkl"
    try:
        elv_plans_df = pd.read_pickle(elv_plans_cache_path)
        print(f"opened {len(elv_plans_df)} elevate plans")

    except FileNotFoundError:
        print(f"fetching plans from elevate, please wait...")
        elv_plans_res = elv.get_plans_by_org(oids=oids, detail=True)
        elv_plans_df = response_to_dataframe(elv_plans_res)
        elv_plans_df = elv_plans_df.rename(columns=ELEVATE_PLAN_RENAME_MAP).drop(columns=COLS_TO_DROP, errors='ignore')
        
        for col in ['plan_year.valid_from', 'plan_year.valid_to']:
            if col not in elv_plans_df:
                print(f"{col} not in plan df")
                continue
            elv_plans_df[col] = pd.to_datetime(elv_plans_df[col])
        elv_plans_df.to_pickle(elv_plans_cache_path)

        print(f"found {len(elv_plans_df)} elevate plans")

    return elv_plans_df


def get_all_cu_clients():
    ''' Get all ClickUp Clients ''' # ~10s
    clients_cache_path = f"{cache_path}/{dt.strftime(today, "%y%m%d")}_ALL_CLIENTS_CLICKUP.pkl"

    try:
        all_clients_df = pd.read_pickle(clients_cache_path)
        print(f"opened {len(all_clients_df)} clickup clients")

    except FileNotFoundError:
        print(f"fetching clients from clickup, please wait...")
        all_clients_res = clickup.get_full_list(model=Client)
        all_clients_df = clickup_response_to_dataframe(all_clients_res)
        all_clients_df = all_clients_df.rename(columns=CLIENT_RENAME_MAP).drop(columns=COLS_TO_DROP + ['list_id', 'task_type'], errors='ignore')
        all_clients_df.to_pickle(clients_cache_path)
        print(f"found {len(all_clients_df)} clickup clients")

    return all_clients_df


def get_all_cu_plans():
    ''' Get all ClickUp Plans ''' # ~30s
    cu_plans_cache_path = f"{cache_path}/{dt.strftime(today, '%y%m%d')}_ALL_PLANS_CLICKUP.pkl"

    try:
        clickup_plans_df = pd.read_pickle(cu_plans_cache_path)
        print(f"opened {len(clickup_plans_df)} clickup plans")

    except FileNotFoundError:

        list_ids = [
            901102729124, # FSA,
            901102729288, # DCA,
            901102729280, # HSA,
            901102729168, # HRA,
            901102745586, # PKG,
            901102745588, # TRN,
            901102745579, # LSA,
            901102782316, # ADO,
            901102745589, # EDU,
        ]

        all_clickup_plans = []
        for list_id in list_ids:
            list_plans = clickup.get_full_list(list_id=list_id)
            if list_plans:
                all_clickup_plans.extend(list_plans)           
        
        clickup_plans_df = clickup_response_to_dataframe(all_clickup_plans)
        clickup_plans_df = clickup_plans_df.rename(columns=CLICKUP_PLAN_RENAME_MAP)

        for col in ['date_plan_start', 'date_plan_end']:
            if col in clickup_plans_df.columns:
                clickup_plans_df[col] = clickup_plans_df[col].apply(
                    lambda x: fix_clickup_date(x) if x is not None else None
                )
                clickup_plans_df[col] = clickup_plans_df[col].apply(
                    lambda x: x.replace(tzinfo=None) if x is not None and hasattr(x, 'tzinfo') else x
                )

        clickup_plans_df.to_pickle(cu_plans_cache_path)
        print(f"found {len(clickup_plans_df)} clickup plans")

    return clickup_plans_df