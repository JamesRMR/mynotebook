import pandas as pd

from rockyclickup.utils import datetime_nearest_day

ELV_ACCOUNT_TYPE_MAP = {
    "DCAP": "DCA",
    "HCFSA": "FSA",
    "PARKING": "PKG",
    "TRANSIT": "TRN",
    "SPECIALTY": "LSA",
    "LIFESTYLE": "LSA",
    "ADOPTION": "ADO",
    "HRA": "HRA",
    "HSA": "HSA",
}


class Merger:
    def __init__(
        self,
        organization_df,
        elv_plan_df,
        client_df,
        cu_plan_df
    ):
        self.organization_df = organization_df.copy().rename(columns={"id": "organization_id"})
        self.elv_plan_df = elv_plan_df.copy().rename(columns={"id": "elv_plan_id"})
        self.client_df = client_df.copy().rename(columns={"id": "client_id", "rmr_code": "rmrcode"})
        self.cu_plan_df = cu_plan_df.copy().rename(columns={"id": "cu_plan_id", "list.name": "cu_account_type"})

        if 'cu_account_type' not in self.cu_plan_df.columns:
            raise ValueError("Column 'list.name' not found in cu_plan_df. Cannot create 'cu_account_type'.")
        
        self.organization_df['rmrcode'] = self.organization_df['external_identifier']
        self.elv_plan_df['cu_account_type'] = self.elv_plan_df['account_type.account_type'].apply(lambda x: ELV_ACCOUNT_TYPE_MAP.get(x))
        print("cu_account_type" in self.elv_plan_df)
        print("cu_account_type" in self.cu_plan_df)

        for col in ['date_plan_start', 'date_plan_end']:
            self.cu_plan_df[col] = self.cu_plan_df[col].apply(lambda x: datetime_nearest_day(x))


    def merge_elevate(self):
        plan_df = self.elv_plan_df.copy()
        org_df = self.organization_df.copy()

        matching_columns = [c for c in plan_df.columns if c in org_df.columns if c != "organization_id"]
        print(matching_columns)

        plan_df = plan_df.rename(columns={c: f"plan_{c}" for c in matching_columns})
        org_df = org_df.rename(columns={c: f"org_{c}" for c in matching_columns})

        elv_merge_df = pd.merge(
            left=plan_df,
            right=org_df,
            on='organization_id',
            how='left'
        )

        return elv_merge_df


    def merge_clickup(self):
        cu_plan_df = self.add_client_id(self.cu_plan_df)

        matching_columns = [c for c in cu_plan_df.columns if c in self.client_df.columns if c != "client_id"]

        client_df = self.client_df.copy().rename(columns={c: f"client_{c}" for c in matching_columns})
        plan_df = cu_plan_df.copy().rename(columns={c: f"plan_{c}" for c in matching_columns})

        cu_merge_df = pd.merge(
            left=plan_df,
            right=client_df,
            on='client_id',
            how='left'
        )

        return cu_merge_df


    def merge_all(self):
        
        # merge orgs w elv plans (on organization id)
        elv_merge_df = self.merge_elevate()


        # merge elv_merge_df with clients (on rmrcode)
        elv_orgs_clients_df = pd.merge(
            left=elv_merge_df,
            right=self.client_df,
            on='rmrcode',
            how='left'
        )

        # extract client ids from plans
        cu_plan_df = self.add_client_id(self.cu_plan_df)

        # add cu_plan_id to merge_df
        elv_orgs_clients_df['cu_plan_id'] = elv_orgs_clients_df.apply(
            lambda row: self.match_clickup_plan(row, cu_plan_df),
            axis=1
        )

        # drop client_id from cu_plan_df
        cu_plan_df = cu_plan_df.drop(columns=['client_id'], errors='ignore')

        merge_df = pd.merge(
            left=elv_orgs_clients_df,
            right=cu_plan_df,
            on='cu_plan_id',
            how='left'
        )

        return merge_df


    def add_client_id(self, cu_plans_df):
        relation_fields = [c for c in cu_plans_df.columns if 'client' in c]

        # turn relation field values to lists
        for col in relation_fields:
            cu_plans_df[col] = cu_plans_df[col].apply(
                lambda x: x if isinstance(x, list) else []
            )

        # combine all client ids from relation fields
        cu_plans_df['client_id_list'] = cu_plans_df.apply(
            lambda row: list(set(sum([row[field] for field in relation_fields], []))),
            axis=1
        )

        # assign single client id
        cu_plans_df['client_id'] = cu_plans_df['client_id_list'].apply(
            self.assign_client_id
        )

        return cu_plans_df


    def assign_client_id(self, client_id_list):
        filtered_list = [
            c for c in client_id_list
            if c in self.client_df['client_id'].unique()
        ]

        unique = list(set(filtered_list))

        if len(unique) == 0:
            return None
        
        return unique[0]


    def match_clickup_plan(self, row, cu_plan_df):
        mapped_account_type = ELV_ACCOUNT_TYPE_MAP.get(row['account_type.account_type'])

        client_match = cu_plan_df['client_id'] == row.get('client_id')
        type_match = cu_plan_df['cu_account_type'] == mapped_account_type.upper()
        date_match = cu_plan_df['date_plan_start'] == row['plan_year.valid_from']

        plan_search = cu_plan_df[client_match & type_match & date_match]

        plan_id_search = list(set(plan_search['cu_plan_id'].to_list()))

        if not plan_id_search:
            return None
        
        if len(plan_id_search) == 1:
            return plan_id_search[0]
        
        return None
    