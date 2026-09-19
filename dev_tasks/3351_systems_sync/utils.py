import pandas as pd
import datetime as dt

from rockyelevate.wrapper import Session as Elevate
from rockyelevate.utils import response_to_dataframe as elv_res_2_df

from rockyclickup.wrapper import Session as Clickup
from rockyclickup.utils import response_to_dataframe as rcu_res_2_df
from rockyclickup.models import Client


class Services():
    def __init__(self):
        self._elv = Elevate(server="PROD", multithread=True, max_threads=40)
        self._rcu = Clickup()


    def get_org_df(self, cache_str_date: str = dt.datetime.now().strftime("%m%d%y")) -> pd.DataFrame:
        org_filename = f"{cache_str_date}_organization_df.csv"

        try:
            org_df = pd.read_csv(org_filename)

        except FileNotFoundError:
            org_res = self._elev.get_orgs_by_id(
                statuses=["PENDING", "ACTIVE", "TERMINATED", "ACTIVATION_FAILED"],
                types=["SYSTEM", "PARTNER", "DISTRIBUTOR", "COMPANY", "SUBSIDIARY", "SUBGROUP"],
            )

            org_df = elv_res_2_df(org_res)
            org_df.to_csv(org_filename)

        return org_df


    def get_client_df(self, cache_str_date: str = dt.datetime.now().strftime("%m%d%y")) -> pd.DataFrame:
        client_filename = f"{cache_str_date}_client_df.csv"

        try:
            client_df = pd.read_csv(client_filename)

        except FileNotFoundError:
            client_res = self._rcu.get_full_list(model=Client)
            client_df = rcu_res_2_df(client_res)
            client_df.to_csv(client_filename)

        return client_df


    def merge_df(self, org_df, client_df):
        merge_df = pd.merge(left=org_df, right=client_df, left_on='external_identifier', right_on='rmr_code')
        return merge_df