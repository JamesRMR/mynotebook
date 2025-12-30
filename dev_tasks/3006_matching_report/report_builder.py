import pandas as pd
import datetime as dt


class ReportBuilder:
    def __init__(self, elv_df, cu_df):
        self.elv_df = elv_df
        self.cu_df = cu_df
        self.now = dt.datetime.now()


    def rmrcode_plans(self, rmrcode):
        elevate_search = self.elv_df[self.elv_df['rmrcode'] == rmrcode]
        clickup_search = self.cu_df[self.cu_df['rmrcode'] == rmrcode]

        return elevate_search, clickup_search


    def organization_name(self, rmrcode):
        elv_plans, cu_plans = self.rmrcode_plans(rmrcode)

        if not elv_plans.empty:
            return elv_plans.iloc[0]['organization_name']
        
        if not cu_plans.empty:
            return cu_plans.iloc[0]['client_name']

    def ids(self, rmrcode):
        elv_plans, cu_plans = self.rmrcode_plans(rmrcode)
        organization_id = ""
        client_id = ""

        if not elv_plans.empty:
            organization_id = elv_plans.iloc[0]['organization_id']
        
        if not cu_plans.empty:
            client_id = cu_plans.iloc[0]['client_id']

        return organization_id, client_id



    def start_date(self, rmrcode):
        elv_plans, cu_plans = self.rmrcode_plans(rmrcode)

        # elevate
        elv_date_df = elv_plans[
            (elv_plans['account_type.account_type'] != "HSA") &    # skip hsa rows
            (elv_plans['plan_year.valid_from'] != "") &            # skip rows w/o valid from date
            (elv_plans['plan_year.valid_from'].notna()) &
            (elv_plans['plan_year.valid_from'] >= dt.datetime(self.now.year - 1, 12, 31))
        ].sort_values(by=['plan_year.valid_from'])
        
        elv_date_values = list(set([dt.datetime.strftime(date, "%m/%d") for date in elv_date_df['plan_year.valid_from'].to_list()]))

        elv_dates = None
        if len(elv_date_values) > 0:
            if len(elv_date_values) == 1:
                elv_dates = elv_date_values[0] # return the only date
            else:
                # print(f"{rmrcode} has more than one elevate plan start date!\n\t{elv_date_values}")
                elv_dates = str(elv_date_values) # return all dates as a stringified list
            
        # clickup
        cu_date_df = cu_plans[
            (cu_plans['cu_account_type'] != "HSA") &
            (cu_plans['date_plan_start'] != "") &
            (cu_plans['date_plan_start'].notna()) &
            (cu_plans['date_plan_start'] >= dt.datetime(self.now.year - 1, 12, 31))
        ].sort_values(by=['date_plan_start'])

        cu_date_values = list(set([dt.datetime.strftime(date, "%m/%d") for date in cu_date_df['date_plan_start'].to_list()]))

        cu_dates = None
        if len(cu_date_values) > 0:
            if len(cu_date_values) == 1:
                cu_dates = cu_date_values[0]
            else:
                # print(f"{rmrcode} has more than one clickup date plan start!\n\t{cu_date_values}")
                cu_dates = str(cu_date_values)

        return elv_dates, cu_dates


    def end_date(self, rmrcode):
        elv_plans, cu_plans = self.rmrcode_plans(rmrcode)

        # elevate
        elv_date_df = elv_plans[
            (elv_plans['account_type.account_type'] != "HSA") &    # skip hsa rows
            (elv_plans['plan_year.valid_to'] != "") &            # skip rows w/o valid from date
            (elv_plans['plan_year.valid_to'].notna()) &
            (elv_plans['plan_year.valid_to'] >= dt.datetime(self.now.year - 1, 12, 31))
        ].sort_values(by=['plan_year.valid_to'])
        
        elv_date_values = list(set([dt.datetime.strftime(date, "%m/%d") for date in elv_date_df['plan_year.valid_to'].to_list()]))

        elv_dates = None
        if len(elv_date_values) > 0:
            if len(elv_date_values) == 1:
                elv_dates = elv_date_values[0] # return the only date
            else:
                # print(f"{rmrcode} has more than one elevate plan end date!\n\t{elv_date_values}")
                elv_dates = str(elv_date_values) # return all dates as a stringified list
            
        # clickup
        cu_date_df = cu_plans[
            (cu_plans['cu_account_type'] != "HSA") &
            (cu_plans['date_plan_end'] != "") &
            (cu_plans['date_plan_end'].notna()) &
            (cu_plans['date_plan_end'] >= dt.datetime(self.now.year - 1, 12, 31))
        ].sort_values(by=['date_plan_end'])

        cu_date_values = list(set([dt.datetime.strftime(date, "%m/%d") for date in cu_date_df['date_plan_end'].to_list()]))

        cu_dates = None
        if len(cu_date_values) > 0:
            if len(cu_date_values) == 1:
                cu_dates = cu_date_values[0]
            else:
                # print(f"{rmrcode} has more than one clickup date plan end!\n\t{cu_date_values}")
                cu_dates = str(cu_date_values)

        return elv_dates, cu_dates


    def HSA_contributions(self, rmrcode):
        return "Need Clarification", "Not On ClickUp"


    def HFSA_limit(self, rmrode):
        return "Need Clarification", "Need Clarification"
    

    def rollover(self, rmrcode):
        elv_plans, cu_plans = self.rmrcode_plans(rmrcode)

        elv_non_hsa = elv_plans[
            elv_plans['account_type.account_type'] != 'HSA'
        ]

        elv_rollover = ""
        elv_rollover_values = elv_non_hsa['plan_account_funding_config.is_rollover.is_rollover'].sort_values(ascending=False).unique()
        if len(elv_rollover_values) == 1:
            elv_rollover = elv_rollover_values[0]
        if len(elv_rollover_values) >= 2:
            elv_rollover = "/".join([str(v) for v in elv_rollover_values])
            if len(elv_rollover_values) > 2:
                print("there shouldnt be more than 2 different values for elevate rollover wtf")

        cu_non_hsa = cu_plans[
            cu_plans['cu_account_type'] != 'HSA'
        ]

        cu_rollover = ""
        cu_rollover_values = cu_non_hsa['rollover'].sort_values(ascending=False).unique()
        if len(cu_rollover_values) == 1:
            cu_rollover = cu_rollover_values[0]
        if len(cu_rollover_values) >= 2:
            cu_rollover = "/".join([str(v) for v in cu_rollover_values])
            if len(cu_rollover_values) > 2:
                print("there shouldnt be more than 2 different values for clickup rollover wtf")

        return elv_rollover, cu_rollover


    def rollover_max(self, rmrcode):
        elv_plans, cu_plans = self.rmrcode_plans(rmrcode)

        elv_non_hsa = elv_plans[
            elv_plans['account_type.account_type'] != 'HSA'
        ]

        has_unlimited = False
        elv_rollover_types = elv_non_hsa['plan_account_funding_config.max_rollover_amount.max_rollover_amount_type'].sort_values().unique()
        if "UNLIMITED" in elv_rollover_types:
            has_unlimited = True

        # get max rollover values for rows that dont have "unlimited" for the max rollover amount type
        elv_rollover_max_values = elv_non_hsa[
            elv_non_hsa['plan_account_funding_config.max_rollover_amount.max_rollover_amount_type'] != "UNLIMITED"
            ][
                'plan_account_funding_config.max_rollover_amount.max_rollover_amount'
            ].unique()

        elv_rollover_max = ", ".join([str(x) for x in elv_rollover_max_values if pd.notna(x)])

        if has_unlimited:
            elv_rollover_max = "UNLIMITED, " + elv_rollover_max

        cu_non_hsa = cu_plans[
            cu_plans['cu_account_type'] != 'HSA'
        ]

        cu_rollover_max = ""
        cu_rollover_max_values = cu_non_hsa['rollover_max'].sort_values().unique()
        if len(cu_rollover_max_values) == 1:
            cu_rollover_max = str(f"{str(cu_rollover_max_values[0])}")

        else:
            cu_rollover_max = ",".join([str(x) for x in cu_rollover_max_values])

        return elv_rollover_max, cu_rollover_max
    
    def carryover_next_year(self, rmrcode):
        elv_plans, _ = self.rmrcode_plans(rmrcode)

        elv_non_hsa = elv_plans[
            elv_plans['account_type.account_type'] != 'HSA'
        ]

        elv_auto_enroll_values = elv_non_hsa[
            'plan_account_funding_config.is_auto_enrollment.is_auto_enrollment'
        ].sort_values(ascending=False).unique()

        elv_auto_enroll = ""
        if len(elv_auto_enroll_values) > 0:
            if len(elv_auto_enroll_values) == 1:
                elv_auto_enroll = elv_auto_enroll_values[0]
            else:
                elv_auto_enroll = "/".join([str(x) for x in elv_auto_enroll_values])

        return elv_auto_enroll, "Not on ClickUp"
    

    def carryover_if_elect(self, rmrcode):
        elv_plans, cu_plans = self.rmrcode_plans(rmrcode)

        cu_non_hsa = cu_plans[cu_plans['cu_account_type'] != 'HSA']

        cu_rollover_eligibility_values = cu_non_hsa['rollover_eligibility'].sort_values(ascending=False).unique()

        cu_roll_eligibility = ""
        if len(cu_rollover_eligibility_values) > 0:
            if len(cu_rollover_eligibility_values) == 1:
                cu_roll_eligibility = cu_rollover_eligibility_values[0]
            else:
                cu_roll_eligibility = "/".join([str(x) for x in cu_rollover_eligibility_values])

        return "Idk where to find on elevate", cu_roll_eligibility


    def limited_purpose(self, rmrcode):
        _, cu_plans = self.rmrcode_plans(rmrcode)

        cu_lpf = True if any([bool(x) for x in cu_plans['lpf']]) else False

        return "Not on Elevate", cu_lpf


    def HSA_offered(self, rmrcode):
        elv_plans, cu_plans = self.rmrcode_plans(rmrcode)

        elv_hsa_offered = (
            False if
                elv_plans[
                    (elv_plans['account_type.account_type'] == "HSA") &
                    (elv_plans['plan_year.valid_from'] >= dt.datetime(self.now.year - 1, 12, 31)) # make sure HSA is current
                ].empty
            else True
        )
        
        cu_hsa_offered = (
            False if
                cu_plans[
                    (cu_plans['cu_account_type'] == "HSA") &
                    (cu_plans['cu_plan_status'].isin(['active', 'setup', 'review'])) # make sure HSA card is active
                ].empty
            else True
        )

        return elv_hsa_offered, cu_hsa_offered

