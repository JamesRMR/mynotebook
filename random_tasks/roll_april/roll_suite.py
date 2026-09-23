import re
import os
import json
import pandas as pd
import datetime as dt
from copy import deepcopy
from dateutil.relativedelta import relativedelta

from rockyelevate.wrapper import Session as elv
from rockyelevate.utils import response_to_dataframe as elv_res_to_df

from rockyclickup.wrapper import Session as rcu
from rockyclickup.utils import response_to_dataframe as rcu_res_to_df, convert_datetime, datetime_nearest_day
from rockyclickup.database_interface import get_all_fields
from rockyclickup.models import (
    Client,
    FSA,
    DCA,
    HSA,
    HRA,
    PKG,
    TRN,
    LSA,
    ADO,
    EDU,
    Task,
    MODEL_LOOKUP
)



class RollSuite:
    def __init__(
            self,
            month_to_roll: dt.datetime = None,
            elv_server: str = "PROD",
            elv_multithread: bool = True,
            elv_max_threads: int = 40,
            cache_path: str = "./roll_cache",
        ):
        
        self.elv_server = elv_server
        self._cache_path = cache_path
        os.makedirs(self._cache_path, exist_ok=True)

        self._rcu = rcu()
        self._elv = elv(elv_server, multithread=elv_multithread, max_threads=elv_max_threads)
        self._now = dt.datetime.now()

        self.get_all_organizations()
        self.get_simple_plans()

        if month_to_roll:
            if not self.is_first_day_of_month(month_to_roll):
                raise ValueError("Month to roll must be first day of the month!")
            self._month_to_roll = month_to_roll
            self._plans_to_roll = self.find_plans_to_roll()
            self._plan_years_to_roll = self.find_plan_years_to_roll()


    def is_first_day_of_month(self, date: dt.datetime = None) -> bool:
        if pd.isna(date) or not isinstance(date, dt.datetime):
            raise ValueError(f"{date} ({type(date)}) is not of type dt.datetime!")
        
        return date.day == 1


    def is_last_day_of_month(self, date: dt.datetime = None) -> bool:
        if pd.isna(date) or not isinstance(date, dt.datetime):
            raise ValueError(f"{date} ({type(date)}) is not of type dt.datetime!")
        
        tomorrow = date + relativedelta(days=1)
        return tomorrow.day == 1


    @property
    def month_to_roll(self):
        return self._month_to_roll


    @month_to_roll.setter
    def month_to_roll(self, new_month: dt.datetime = None):
        if not self.is_first_day_of_month(new_month):
            raise ValueError("Month to roll must be first day of the month!")
        
        self._month_to_roll = new_month
        self._plans_to_roll = self.find_plans_to_roll()
        self._plan_years_to_roll = self.find_plan_years_to_roll()

    
    def get_all_organizations(self, refresh: bool = False) -> pd.DataFrame:
        filename = f"{self._cache_path}/{self._now.strftime('%y%m%d')}_all_orgs.json"
        try:
            if refresh:
                raise FileNotFoundError()
            
            with open(filename, 'r') as f:
                all_orgs = json.load(f)

            print(f"{len(all_orgs)} orgs opened from cache")

        except FileNotFoundError:
            # all_orgs = self._elv.get_organizations(types=["SYSTEM", "PARTNER", "DISTRIBUTOR", "COMPANY", "SUBSIDIARY", "SUBGROUP"])

            all_orgs = self._elv.get_orgs_by_id(children=False)

            with open(filename, 'w') as f:
                json.dump(all_orgs, f)

            print(f"{len(all_orgs)} orgs fetched")


        org_df = elv_res_to_df(all_orgs)

        self._external_identifier_map = {r['id']: r['external_identifier'] for _, r in org_df.iterrows()}

        self._all_orgs = org_df
        return org_df
    

    def filter_active_organizations(self, organizations: pd.DataFrame = pd.DataFrame()):
        if (
            isinstance(organizations, pd.DataFrame)
            and organizations.empty
        ) or (
            not isinstance(organizations, pd.DataFrame)
            and not organizations
        ): return organizations
        
        df = organizations.copy()

        df = df[df['parent_id'] == 5012]
        df = df[df['organization_status_type'].isin(['ACTIVE'])]

        return df


    def get_simple_plans(self, refresh = False) -> pd.DataFrame:
        if not hasattr(self, "_all_orgs") or self._all_orgs.empty:
            self.get_all_organizations()

        filename = f"{self._cache_path}/{self._now.strftime('%y%m%d')}_simple_plans.json"
        try:
            if refresh:
                raise FileNotFoundError()

            with open(filename, 'r') as f:
                simple_plans = json.load(f)

            print(f"{len(simple_plans)} simple plans opened from cache")

        except FileNotFoundError:
            org_ids = list(self._all_orgs['id'].unique())
            simple_plans = self._elv.get_plans_by_org(oids=org_ids, detail=False)

            with open(filename, 'w') as f:
                json.dump(simple_plans, f)

            print(f"{len(simple_plans)} fetched")

        plan_df = elv_res_to_df(simple_plans)
        for col in ['plan_year.valid_from', 'plan_year.valid_to']:
            plan_df[col] = pd.to_datetime(plan_df[col])

        self._all_plans_simple = plan_df
        return self._all_plans_simple


    def find_plans_to_roll(self) -> pd.DataFrame:
        if not hasattr(self, "_all_plans_simple") or self._all_plans_simple.empty:
            self.get_simple_plans()

        df = self._all_plans_simple.copy()

        # filter out short plans (and extra long ones)
        df['plan_length'] = df.apply(lambda row: (row['plan_year.valid_to'] - row['plan_year.valid_from']).days, axis=1)
        df = df[
            (df['plan_length'] > 360) &
            (df['plan_length'] <= 366)
        ]

        # filter out plans that don't start on the first day of the month
        df = df[df['plan_year.valid_from'].apply(lambda x: x.day == 1)]

        # filter out plans that don't end on the last day of the month
        df = df[df['plan_year.valid_to'].apply(lambda x: self.is_last_day_of_month(x))]

        # narrow to plans that are ending the day before `month_to_roll` datetime parameter
        df = df[df['plan_year.valid_to'].apply(lambda x: (self._month_to_roll - x).days == 1)]

        # get detailed plans for narrowed simple plans
        plan_ids = [int(i) for i in df['id'].unique()]
        elv_detail_response = self._elv.get_plans_by_id(pids=plan_ids)
        detail_df = elv_res_to_df(elv_detail_response)

        # convert dates
        for col in ['plan_year.valid_from', 'plan_year.valid_to']:
            detail_df[col] = pd.to_datetime(detail_df[col])

        # filter out plans that have alrady beed rolled
        already_rolled = []
        for index, row in detail_df.iterrows():
            matching = self._all_plans_simple[
                (self._all_plans_simple['organization_id'] == row['organization_id']) &
                (self._all_plans_simple['account_type'] == row['account_type.account_type'])
            ]
            if (matching['plan_year.valid_from'] > row['plan_year.valid_to']).any():
                already_rolled.append(index)

        detail_df = detail_df.drop(index=already_rolled)

        return detail_df


    def verbose_plans_to_roll(self) -> dict:
        '''
            just double checking for plans that have already been rolled
        '''

        simple_plans = self._all_plans_simple

        rolls_needed = {}
        for org_id, org_plans in self._plans_to_roll.groupby("organization_id"):

            all_org_plans = simple_plans[simple_plans['organization_id'] == org_id]
            print(f"org {org_id}: {len(org_plans)} plans to roll ({len(all_org_plans)} total)")

            for index, row in org_plans.iterrows():

                plan_id = row['id']

                print(f"   ({plan_id}) {row['plan_code']}   {row['account_type.account_type']:<10} {row['plan_year.valid_from'].strftime('%m/%d/%Y')} - {row['plan_year.valid_to'].strftime('%m/%d/%Y')}")

                matching_account = all_org_plans[
                    all_org_plans['account_type'] == row['account_type.account_type']
                ]

                roll_needed = True
                for _, r in matching_account.iterrows():
                    if r['plan_year.valid_from'] > row['plan_year.valid_to']:
                        print(f"\t{'-' if r['plan_year.valid_from'] > row['plan_year.valid_to'] else 'x'}  {r['plan_code']:<27} {'already rolled!'}")
                        roll_needed = False

                if roll_needed:
                    print(f"\tRoll Needed!")
                    if org_id not in rolls_needed:
                        rolls_needed[org_id] = []

                    rolls_needed[org_id].append(row['id'])

                print()

        return rolls_needed


    def build_new_plan_year_bodies(self) -> list[dict]:
        plan_year_df = self._plans_to_roll[['organization_id', "plan_year.id", "plan_year.valid_from", "plan_year.valid_to"]].drop_duplicates()

        new_plan_year_bodies = []
        for _, row in plan_year_df.iterrows():
            new_valid_from = row['plan_year.valid_to'] + relativedelta(days=1)
            
            # make sure new valid from is the first day of the month
            if new_valid_from.day != 1:
                raise ValueError(f"{new_valid_from.strftime('%m/%d/%Y')} is not the first day of the month ({row['organization_id']})")
            
            new_valid_to = (new_valid_from + relativedelta(years=1)) - relativedelta(days=1)

            # make sure new valid to is the last day of the month
            if (new_valid_to + relativedelta(days=1)).day != 1:
                raise ValueError(f"{new_valid_to.strftime('%m/%d/%Y')} is not the last day of the month ({row['organization_id']})")
            
            valid_from_str = new_valid_from.strftime('%m/%d/%Y')
            valid_to_str = new_valid_to.strftime('%m/%d/%Y')

            new_plan_year_bodies.append({
                "organization_id": row['organization_id'],
                "name": f"{valid_from_str} - {valid_to_str}",
                "valid_from": valid_from_str,
                "valid_to": valid_to_str,
                "prior_plan_year_id": row['plan_year.id']
            })

        return new_plan_year_bodies
    

    def find_plan_years_to_roll(self) -> pd.DataFrame:
        needed_plan_years = self.build_new_plan_year_bodies()
        existing_plan_years = self._elv.get_plan_years(oids=[y.get("organization_id") for y in needed_plan_years])
        existing_plan_year_df = elv_res_to_df(existing_plan_years)

        df = elv_res_to_df(needed_plan_years)
        df['id'] = None

        for index, row in df.iterrows():
            org_pys = existing_plan_year_df[existing_plan_year_df['organization_id'] == row['organization_id']]

            matching_name = org_pys[org_pys['name'] == row['name']]
            if not matching_name.empty:
                df.loc[index, 'id'] = matching_name.iloc[0]['id']
                continue

            matching_dates = org_pys[
                (org_pys['valid_from'] == row['valid_from']) &
                (org_pys['valid_to'] == row['valid_to'])
            ]
            if not matching_dates.empty:
                df.loc[index, 'id'] = matching_dates.iloc[0]['id']
                continue

        to_create = df[df['id'].isna()].drop(columns="id")
        return to_create
    

    def create_plan_years(self, plan_year_bodies):
        if not plan_year_bodies: return ([], [])

        elv_responses = []
        exceptions = []
            for pyb in plan_year_bodies:
                key = f"{pyb.get('organization_id')}_{pyb.get('prior_plan_year_id')}"
            try:
                elv_res = self._elv.post(f"{self._elv.basepath}/plan-years", payload=pyb)

                if isinstance(elv_res, tuple):
                    elv_responses.append({key: elv_res[1].json()})
                else:
                    elv_responses.append({key: elv_res.json()})
            except Exception as e:
                exceptions.append({key: str(e)})

        now_timestep = int(dt.datetime.now().timestamp())
        my_str = self.month_to_roll.strftime('%b%Y').lower()

        if elv_responses:
            res_filename = f"{my_str}_create_plan_year_responses_{now_timestep}.json"
            with open(res_filename, "w") as f:
                json.dump(elv_responses, f)
            print(f"elevate responses saved!\n\t`{res_filename}")

        if exceptions:
            exc_filename = f"{my_str}_create_plan_year_exceptions_{now_timestep}.json"
            with open(exc_filename, "w") as f:
                json.dump(exceptions, f)
            print(f"exceptions saved!\n\t`{exc_filename}")

        self._plan_years_to_roll = self.find_plan_years_to_roll()

        return (elv_responses, exceptions)


        
    def _get_detailed_plans(self, plan_ids: list[int]) -> list[dict]:
        filename = f"{self._cache_path}/{self._now.strftime('%y%m%d')}_detailed_plans.json"

        try:
            with open(filename, "r") as f:
                current = json.load(f)

        except Exception as e:
            current = []

        current_plan_ids = [p.get("id", None) for p in current]
        missing_plan_ids = [p for p in plan_ids if p not in current_plan_ids]


        if not missing_plan_ids:
            return [p for p in current if p.get("id") in plan_ids]
        
        print(f"fetching details for {len(missing_plan_ids)} plans")
        missing_plan_responses = self._elv.get_plans_by_id(pids=missing_plan_ids)

        new_json = current + missing_plan_responses
        with open(filename, "w") as f:
            json.dump(new_json, f)

        return [p for p in new_json if p.get("id") in plan_ids]


    def create_naked_bodies(self, plans_to_roll: pd.DataFrame = pd.DataFrame()) -> list[dict]:
        if plans_to_roll is None or plans_to_roll.empty:
            print("no plans were sent to roll")
            return []
        
        plan_years_to_roll = self._plan_years_to_roll
        if not plan_years_to_roll.empty:
            raise ValueError(f"missing {len(plan_years_to_roll)} plan years, create them before rolling plans\nuse RollSuite.find_plan_years_to_roll() to identify")

        plan_ids = [int(p) for p in plans_to_roll['id'].unique()]
        plan_responses = self._get_detailed_plans(plan_ids)
        
        org_ids = [int(p) for p in plans_to_roll['organization_id'].unique()]
        plan_years = self._elv.get_plan_years(oids=org_ids)

        rev_plan_year_map = {
            p.get("prior_plan_year_id"): p.get("id")
            for p in plan_years
        }

        def _generate_new_plan_code(old_plan, new_valid_from, new_valid_to):
            org_row = self._all_orgs[self._all_orgs['id'] == old_plan.get("organization_id")]
            if org_row.empty:
                raise ValueError(f"Cannot find organization for plan {old_plan.get('id')} ({old_plan.get('organization_id')})")

            rmrcode = org_row.iloc[0]['external_identifier']
            plan_type = ELV_ACCOUNT_TYPE_MAP.get(old_plan.get("account_type", {}).get("account_type"), None)
            valid_from_str = new_valid_from.strftime("%m%d%Y")
            valid_to_str = new_valid_to.strftime("%m%d%Y")

            missing_p = []
            for k, v in {
                "rmrcode": rmrcode,
                "plan_type": plan_type,
                "valid_from_str": valid_from_str,
                "valid_to_str": valid_to_str,
            }.items():
                if not v:
                    missing_p.append(k)

            if missing_p:
                raise ValueError(f"Missing properties for plan code ({old_plan.get('id', '')}):\n{missing_p}")

            return f"{rmrcode}{plan_type}{valid_from_str}{valid_to_str}"


        def _generate_new_plan_name(old_plan, new_valid_from) -> str:

            # get current plan name
            new_plan_name = old_plan.get("name", {}).get("name", None)
            if not new_plan_name:
                raise ValueError(f"Invalid prior plan name: {new_plan_name}")

            # finnd all numbers in plan name
            number_substrings = re.findall(r'\d+', new_plan_name)

            # loop through all numbers
            for num in number_substrings:
                # if the number is larger than `2020` remove it
                if int(num) > 2020:
                    new_plan_name = new_plan_name.replace(num, "")

            # split the name on spaces and rejoin.
            # forgot why i did this, prolly to fix formatting issues
            name_split = new_plan_name.split(" ")
            name_split = [s for s in name_split if s != '']
            new_plan_name = " ".join(name_split)

            # return early if it's an hsa
            if (
                pd.notna(old_plan.get("account_type", {}).get("account_type", "").lower())
                and old_plan.get("account_type", {}).get("account_type").lower() == "hsa"
            ) or (
                pd.notna(ELV_ACCOUNT_TYPE_MAP.get(old_plan.get("account_type", {}).get("account_type")))
                and ELV_ACCOUNT_TYPE_MAP.get(old_plan.get("account_type", {}).get("account_type")).lower() == "hsa"
            ):
                return new_plan_name

            # otherwise add the current plan year to the new plan name
            new_plan_name = f"{new_plan_name} {new_valid_from.year}"
            return new_plan_name


        naked_bodies = []
        for old_plan in plan_responses:

            prior_plan_id = old_plan.get("id", None)
            org_id = old_plan.get("organization_id", None)

            new_valid_from = pd.to_datetime(old_plan.get("plan_year", {}).get("valid_to", None)) + relativedelta(days=1)
            if not self.is_first_day_of_month(new_valid_from):
                raise ValueError(f"New valid from ({new_valid_from.strftime('%m/%d/%Y')}) for plan ({prior_plan_id}) is not the first day of the month")

            new_valid_to = new_valid_from + relativedelta(years=1) - relativedelta(days=1)
            if not self.is_last_day_of_month(new_valid_to):
                raise ValueError(f"New valid to ({new_valid_to.strftime('%m/%d/%Y')}) for plan ({prior_plan_id}) is not the last day of the month")

            plan_code = _generate_new_plan_code(old_plan, new_valid_from, new_valid_to)
            name = _generate_new_plan_name(old_plan, new_valid_from)
            parent_id = ELV_TEMPLATE_IDS.get(self.elv_server, {}).get(old_plan.get("account_type", {}).get("account_type", None))
            plan_year_id = rev_plan_year_map.get(old_plan.get("plan_year_id"), None)

            # make sure the plan year valid from date matches the month we want to roll
            plan_year = [py for py in plan_years if py.get("id") == plan_year_id]
            if not plan_year:
                raise ValueError(f"No plan year found for {old_plan.get('id', '')}")
            plan_year = plan_year[0]

            py_valid_from = pd.to_datetime(plan_year.get("valid_from", None))
            if not all([
                py_valid_from > self._month_to_roll - relativedelta(days=1),
                py_valid_from < self._month_to_roll + relativedelta(days=1)
            ]):
                raise ValueError(f"Selected plan year ({plan_year.get('valid_from')}-{plan_year.get('valid_to')}) does not match the month we want to roll ({self._month_to_roll.strftime('%m/%d/%Y')})")
            
            missing_props = []
            for k, v in {"org_id": org_id, "plan_code": plan_code, "name": name, "prior_plan_id": prior_plan_id, "parent_id": parent_id, "plan_year_id": plan_year_id}.items():
                if not v:
                    missing_props.append(k)

            if missing_props:
                raise ValueError(f"Missing Properties (plan id: `{old_plan.get('id')}`): \n{missing_props}")

            naked_bodies.append({
                "organization_id": org_id,
                "plan_code": plan_code,
                "name": {
                    "name": name,
                    "name_state": "MODIFIABLE"
                },
                "prior_plan_id": prior_plan_id,
                "parent_id": parent_id,
                "plan_year_id": plan_year_id,
                "is_plan": True
            })

        return naked_bodies


    def send_naked_bodies(self, naked_bodies: list[dict] = []) -> tuple[list, list]:
        if not naked_bodies: return ([], [])

        endpoint = f"{self._elv.basepath}/plans"

        elv_responses = []
        exceptions = []
        for request_body in naked_bodies:
            try:
                prior_plan_id = request_body.get("prior_plan_id", None)
                if not prior_plan_id:
                    raise ValueError("prior_plan_id is required!")

                elv_res = self._elv.post(endpoint, request_body)

                if isinstance(elv_res, tuple):
                    elv_responses.append({prior_plan_id: elv_res[1].json()})
                
                else:
                    elv_responses.append({prior_plan_id: elv_res.json()})

            except Exception as e:
                exceptions.append({"plan_id": request_body.get("id") or request_body.get("prior_plan_id"), "error": str(e)})

        now_timestamp = int(dt.datetime.now().timestamp())
        my_str = self.month_to_roll.strftime('%b%Y').lower()

        if elv_responses:
            res_filename = f"{my_str}_naked_body_responses_{now_timestamp}.json"
            with open(res_filename, 'w') as f:
                json.dump(elv_responses, f)
            print(f"elevate responses saved!\n\t`{res_filename}`")

        if exceptions:
            exc_filename = f"{my_str}_naked_body_exceptions_{now_timestamp}.json"
            with open(exc_filename, 'w') as f:
                json.dump(exceptions, f)
            print(f"exceptions saved!\n\t`{exc_filename}`")

        return (elv_responses, exceptions)


    def create_update_bodies(self, plan_ids: list[int] = []) -> list[dict]:
        if not plan_ids: return []

        naked_plans = self._elv.get_plans_by_id(pids=plan_ids)

        prior_plan_ids = [p.get("prior_plan_id", None) for p in naked_plans]
        if None in prior_plan_ids:
            missing_prior_plans = [p for p in naked_plans if not p.get("prior_plan_id", None)]
            raise ValueError(f"{len(missing_prior_plans)} plans are missing prior plan ids: {missing_prior_plans}")
        
        prior_plans = self._elv.get_plans_by_id(pids=prior_plan_ids)
        prior_plan_map = {p.get("id"): p for p in prior_plans}
        del prior_plans

        update_bodies = []
        for plan in naked_plans:
            prior_plan = prior_plan_map.get(plan.get("prior_plan_id", "no prior plan id"), None)
            if not prior_plan:
                raise ValueError(f"plan {plan.get('id')} is missing prior plan id")

            updated_body = deepcopy(plan)

            for field in [f for f in FIELDS_TO_POP if f in updated_body]:
                updated_body.pop(field, None)

            for field in [f for f in FIELDS_TO_COPY if f in prior_plan]:
                updated_body[field] = prior_plan[field]

            for field, value in FIELDS_TO_SET.items():
                updated_body[field] = value

            update_bodies.append(updated_body)

        return update_bodies


    def send_update_bodies(self, update_bodies: list[dict] = []) -> tuple[list, list]:
        if not update_bodies: return ([], [])

        elv_responses = []
        exceptions = []
        for request_body in update_bodies:
            try:
                plan_id = request_body.get("id", None)
                if not plan_id:
                    raise ValueError("Plan ID is required to update!")
                endpoint = f"{self._elv.basepath}/plans/{plan_id}"

                elv_res = self._elv.put(endpoint, request_body)

                if isinstance(elv_res, tuple):
                    elv_responses.append({plan_id: elv_res[1].json()})
                
                else:
                    elv_responses.append({plan_id: elv_res.json()})

            except Exception as e:
                exceptions.append({"plan_id": request_body.get("id"), "error": str(e)})

        now_timestamp = int(dt.datetime.now().timestamp())
        my_str = self.month_to_roll.strftime('%b%Y').lower()

        if elv_responses:
            res_filename = f"{my_str}_update_plan_responses_{now_timestamp}.json"
            with open(res_filename, 'w') as f:
                json.dump(elv_responses, f)
            print(f"elevate responses saved!\n\t`{res_filename}`")

        if exceptions:
            exc_filename = f"{my_str}_update_plan_exceptions_{now_timestamp}.json"
            with open(exc_filename, 'w') as f:
                json.dump(exceptions, f)
            print(f"exceptions saved!\n\t`{exc_filename}`")

        return (elv_responses, exceptions)
    

    def _get_all_clients(self, refresh: bool = False):
        filename = f"{self._cache_path}/{self._now.strftime('%y%m%d')}_all_clients.json"
        try:
            if refresh:
                raise FileNotFoundError()
            
            with open(filename, 'r') as f:
                all_clients = json.load(f)
            
            print(f"{len(all_clients)} clients opened from cache")

        except FileNotFoundError as e:
            
            all_clients = self._rcu.get_full_list(model=Client)

            with open(filename, 'w') as f:
                json.dump(all_clients, f)

            print(f"{len(all_clients)} clients fetched")

        self._all_clients = rcu_res_to_df(all_clients)
        self._rmrcode_map = {r['id']: r['rmr_code'] for _, r in self._all_clients.iterrows()}
        return self._all_clients    


    def _get_all_clickup_plans(self, refresh: bool = False):
        filename = f"{self._cache_path}/{self._now.strftime('%y%m%d')}_all_rcu_plans.json"
        try:
            if refresh:
                raise FileNotFoundError()
            
            with open(filename, 'r') as f:
                all_plans = json.load(f)

            print(f"{len(all_plans)} plans opened from cache")

        except FileNotFoundError as e:
            all_plans = []
            for model in [FSA, DCA, HSA, HRA, PKG, TRN, LSA, ADO, EDU]:
                rcu_res = self._rcu.get_full_list(model=model)
                all_plans.extend(rcu_res)

            with open(filename, 'w') as f:
                json.dump(all_plans, f)

            print(f"{len(all_plans)} plans fetched")


        all_plans_df = rcu_res_to_df(all_plans)
        for col in ['date_plan_start', 'date_plan_end']:
            all_plans_df[col] = pd.to_datetime(all_plans_df[col], utc=True)
            all_plans_df[col] = all_plans_df[col].dt.tz_localize(None)
            all_plans_df[col] = all_plans_df[col].apply(lambda x: datetime_nearest_day(x).date() if x else None)

        self._all_clickup_plans = all_plans_df
        return self._all_clickup_plans


    def merge_client_plans(self):

        if not hasattr(self, "_all_clickup_plans"):
            self._get_all_clickup_plans()

        if not hasattr(self, "_all_clients"):
            self._get_all_clients()
        
        plans_df = self._all_clickup_plans.copy()

        relation_fields = [c for c in plans_df.columns if 'client' in c]

        for col in relation_fields:
            plans_df[col] = plans_df[col].apply(
                lambda x: x if isinstance(x, list) else []
            )

        plans_df["client_id"] = plans_df.apply(
            lambda row: list(set(sum([row[field] for field in relation_fields], []))),
            axis=1
        )

        plans_df["client_id"] = plans_df["client_id"].apply(
            lambda x: x[0] if len(x) > 0 else None
        )

        plans_df = plans_df.drop(columns=relation_fields)

        client_df = self._all_clients.copy()

        matching_columns = [c for c in plans_df.columns if c in client_df.columns]

        client_df = client_df.rename(columns={c: f"client_{c}" for c in matching_columns})
        plans_df = plans_df.rename(columns={c: f"plan_{c}" for c in matching_columns})

        merge_df = pd.merge(
            left=plans_df,
            right=client_df,
            on="client_id",
            how="left"
        )

        self._client_plans = merge_df
        return self._client_plans


    def get_plans_to_align(self, refresh: bool = True):
        if not hasattr(self, "_client_plans") or self._client_plans.empty or refresh:
            self.merge_client_plans()

        elv_plans = self._all_plans_simple[self._all_plans_simple['plan_year.valid_from'] == self._month_to_roll]
        rev_rmrcode_map = {v: k for k, v in self._rmrcode_map.items()}

        elv_plans["cu_account_type"] = elv_plans['account_type'].map(ELV_ACCOUNT_TYPE_MAP)

        print(f"{len(elv_plans)} elv plans start on {self._month_to_roll.strftime("%m/%d/%Y")}")

        plans_to_align = []
        for org_id, org_plans in elv_plans.groupby("organization_id"):
            print("\n\n"+"_"*70)
            print(f"Organization  {org_id:>10}  {len(org_plans)} plan{"s" if len(org_plans) != 1 else ""}")

            external_identifier = self._external_identifier_map.get(org_id, None)
            client_id = rev_rmrcode_map.get(external_identifier, None)

            if not external_identifier or not client_id:
                raise ValueError(f"Unable to find Client ({external_identifier}, {client_id})")

            client_plans = self._client_plans[
                (self._client_plans["client_id"] == client_id)
            ]

            print(f"Client {'#' + str(client_id):>17}  {len(client_plans)} plan{"s" if len(client_plans) != 1 else ""} (total)")

            for _, org_plan in org_plans.iterrows():
                print(f"   -  {'(' + str(org_plan['account_type']) + ')':<11} {org_plan['id']:<7} {org_plan['plan_code']}")

                mask_account_type = (client_plans['plan_list.name'] == org_plan['cu_account_type'])
                mask_start_date = (
                    (client_plans['date_plan_start'] > org_plan['plan_year.valid_from'] - relativedelta(days=2)) &
                    (client_plans['date_plan_start'] < org_plan['plan_year.valid_from'] + relativedelta(days=2))
                )

                if org_plan['cu_account_type'] == "HSA":
                    matches = client_plans[mask_account_type]
                else:
                    matches = client_plans[
                        mask_account_type &
                        mask_start_date
                    ]

                if matches.empty:
                    print(f"\t\t\t  No ClickUp Matches!")

                    plan_to_align = {
                        "rmrcode": external_identifier,
                        "org_id": org_id,
                        "client_id": client_id,
                        "elv_plan_id": org_plan['id'],
                        "account_type": ELV_ACCOUNT_TYPE_MAP.get(org_plan['account_type'], "UNKNOWN ACCOUNT TYPE")
                    }

                    prior_clickup_matches = client_plans[
                        mask_account_type &
                        # (client_plans['date_plan_start'] > org_plan['plan_year.valid_from'] - relativedelta(years=1, days=2))
                        (client_plans['date_plan_start'] < org_plan['plan_year.valid_from'])
                    ].sort_values(by='date_plan_start', ascending=False)

                    if not prior_clickup_matches.empty:
                        plan_to_align['prior_plan_id'] = prior_clickup_matches.iloc[0]['plan_id']

                    plans_to_align.append(plan_to_align)

                else:
                    match = matches.iloc[0]
                    print(f"{'#' + str(match['plan_id']):>24}  Match!")


        plans_to_align_df = pd.DataFrame(plans_to_align)

        plans_to_align_df = plans_to_align_df[
            ~((plans_to_align_df['account_type'] == "HSA") &
            (plans_to_align_df['prior_plan_id'].notna()))
        ]
        return plans_to_align_df


    def get_detailed_plans(self, plan_ids: list[int] = []):
        filename = f"{self._now.strftime("%y%m%d")}_detailed_plans.json"

        try:
            with open(filename, 'r') as f:
                cached_plans = json.load(f)
            
            plans_found = [p for p in cached_plans if p.get("id") in plan_ids]

        except FileNotFoundError as e:
            plans_found = []

        plans_to_fetch = [i for i in plan_ids if i not in [p.get("id") for p in plans_found]]

        elv_res = self._elv.get_plans_by_id(plans_to_fetch)
        if isinstance(elv_res, tuple):
            raise ValueError(str(elv_res[1].json()))

        with open(filename, 'a'):
            json.dump(elv_res)

        plans_found.extend(elv_res)
        return plans_found


    def create_clickup_cards(self, plans_to_align: pd.DataFrame = pd.DataFrame()):
        if (
            isinstance(plans_to_align, pd.DataFrame)
            and plans_to_align.empty
        ) or (
            not isinstance(plans_to_align, pd.DataFrame)
            and not plans_to_align
        ):
            return []

        def create_task_name(row):
            name = f"{row['rmrcode']} {row['cu_account_type']}"

            if row['cu_account_type'] == "HSA":
                return name
            
            name = f"{name} {row['plan_year.valid_from'].year}"
            return name
        
        # get prior plan card
        # prior_plan_ids = list(plans_to_align['prior_plan_id'].unique())
        # clickup_response = self._rcu.get_tasks(prior_plan_ids)

        # get elv plan details
        elv_plan_ids = [int(i) for i in plans_to_align['elv_plan_id'].unique()]
        detailed_plans = self._elv.get_plans_by_id(pids=elv_plan_ids)
        detailed_plan_df = elv_res_to_df(detailed_plans)
        detailed_plan_df['rmrcode'] = detailed_plan_df['organization_id'].map(self._external_identifier_map)
        detailed_plan_df['cu_account_type'] = detailed_plan_df['account_type.account_type'].map(ELV_ACCOUNT_TYPE_MAP)
        for col in ['plan_year.valid_from', 'plan_year.valid_to']:
            detailed_plan_df[col] = pd.to_datetime(detailed_plan_df[col])

        # setup roll df with task names
        roll_df = pd.DataFrame()
        roll_df['name'] = detailed_plan_df.apply(create_task_name, axis=1)
        roll_df['at'] = detailed_plan_df['cu_account_type']

        # fields to copy directly from elevate
        for rcu, elv in ELV_FIELDS_TO_COPY_TO_CLICKUP.items():
            roll_df[rcu] = detailed_plan_df[elv]

        # fields that require some shenanigans
        roll_df['annual_election_auto_adjust'] = detailed_plan_df['plan_primary_config.max_election_amount_type.max_election_amount_type'].apply(lambda x: True if x == "IRS_LIMIT" else False)
        roll_df['annual_election_max'] = detailed_plan_df.apply(
            lambda row:
                0.0 if row['plan_primary_config.max_election_amount_type.max_election_amount_type'] == "UNLIMITED"
                else row['plan_primary_config.max_election_amount_type.max_election_amount'],
            axis=1
        )
        roll_df['run_out_termed_ee_matches_plan'] = detailed_plan_df['plan_coverage_config.claims_deadline_end_of_coverage_type.claims_deadline_end_of_coverage_type'].apply(lambda x: x == "PRE_DEFINED_END_DATE")

        # fields to copy from from previous card
        
        
        for field in ["description"]:
            roll_df[field] = roll_df['elv_id'].map()

        # add relation fields back (ALL client_* relation fields are added but most get removed when rcu model gets initialized) 
        client_id_map = {r['elv_plan_id']: r['client_id'] for _, r in plans_to_align.iterrows()}
        plan_types = [m.lower() for m in REV_MODEL_LOOKUP.keys()]
        for col in [f'client_{c}' for c in plan_types]:
            roll_df[col] = roll_df['elv_id'].map(client_id_map)

        # convert rows to dicts
        plan_dicts = [r.to_dict() for _, r in roll_df.iterrows()]
        all_rcu_db_fields = get_all_fields()
        field_map = {f.custom_name: f for f in all_rcu_db_fields}
        
        clickup_cards = []
        for plan_dict in plan_dicts:
            new_dict = {}
            for key, value in plan_dict.items():
            
                if (isinstance(value, list) and len(value) == 0) or (not isinstance(value, list) and pd.isna(value)):
                    continue

                if key == "list_id":
                    new_dict[key] = int(value)
                    continue

                if key not in field_map:
                    new_dict[key] = value
                    continue

                field_type = field_map.get(key).type

                match field_type:
                    case "list_relationship":
                        if isinstance(value, list):
                            new_dict[key] = value
                        else:
                            new_dict[key] = [value]

                    case "users":
                        if isinstance(value, list):
                            new_dict[key] = value
                        else:
                            new_dict[key] = [value]

                    case "short_text":
                        new_dict[key] = str(value)

                    case "number":
                        new_dict[key] = int(value)

                    case "currency":
                        new_dict[key] = float(value)

                    case "checkbox": 
                        new_dict[key] = bool(value)

                    case "date":
                        # new_dict[key] = convert_datetime(value, correct_tz_offset=True)
                        v = pd.to_datetime(value)
                        new_dict[key] = convert_datetime(v.to_pydatetime())

                    case _:
                        pass
            
            model = REV_MODEL_LOOKUP.get(plan_dict.get("at", None))
            if not model: raise ValueError(f"rcu model not found for {plan_dict.get("elv_id")} ({plan_dict.get("at")})")

            clickup_card = model(**{k: v for k, v in new_dict.items() if k in dir(model)})
            clickup_cards.append(clickup_card)
        
        return clickup_cards
    
    def send_clickup_cards(self, clickup_cards: list[Task]):
        if not clickup_cards: return []

        for card in clickup_cards:
            print(card.elv_id) 