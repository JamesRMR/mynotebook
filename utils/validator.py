import pandas as pd

class Validator(pd.DataFrame):
    def __init__(self, df=None, error_masks=None, warning_masks=None, *args, **kwargs):
        if df is None:
            in_df = pd.DataFrame()
        else:
            in_df = df.copy()

        super().__init__(in_df, *args, **kwargs)
        
        object.__setattr__(self, 'error_masks', error_masks or [])
        object.__setattr__(self, 'warning_masks', warning_masks or [])

        if 'error' not in self.columns:
            self['error'] = pd.Series([[] for _ in range(len(self))], index=self.index)
        
        if 'warning' not in self.columns:
            self['warning'] = pd.Series([[] for _ in range(len(self))], index=self.index)

    def add_error(self, mask, err_message):
        if any(mask):
            self.loc[mask, 'error'] = self.loc[mask, 'error'].apply(
                lambda x: x + [err_message] if (isinstance(x, list) and err_message not in x) else [err_message]
            )
        
    def add_warning(self, mask, warning_message):
        if any(mask):
            self.loc[mask, 'warning'] = self.loc[mask, 'warning'].apply(
                lambda x: x + [warning_message] if (isinstance(x, list) and warning_message not in x) else [warning_message]
            )

    def validate(self):
        try:
            for msg, mask_func in self.error_masks:
                mask = mask_func(self)
                self.add_error(mask, msg)
        except KeyError as e:
            all_rows_mask = pd.Series([True] * len(self), index=self.index)
            self.add_error(all_rows_mask, f"Column {e} not found for validation")

        try:
            for msg, mask_func in self.warning_masks:
                mask = mask_func(self)
                self.add_warning(mask, msg)
        except KeyError as e:
            all_rows_mask = pd.Series([True] * len(self), index=self.index)
            self.add_error(all_rows_mask, f"Column {e} not found for validation")

        return self
    

error_masks = [
    (
        "auto-renew not turned on",
        lambda df: df['elevate_auto_renew'] != 'Active'
    ),
    (
        "specialty account",
        lambda df: (df['prior_plan_id'] == "43758") | (df['rmrcode'] == "RMRHSAUMB")
    ),
    (
        "`template` in plan name",
        lambda df: df['elv_plan_name'].str.lower().str.contains("template", na=False)
    ),
    (
        "`delete` in plan name",
        lambda df: df['elv_plan_name'].str.lower().str.contains("delete", na=False)
    ),
    (
        # checks if valid_from is the first day of the month
        "invalid valid_from", 
        lambda df: 
            (df['plan_year.valid_from'].notna()) &
            (df['plan_year.valid_from'].dt.day != 1)
    ),
    (
        # checks if valid_to is the last day of the month
        "invalid valid_to",
        lambda df: 
            (df['plan_year.valid_to'].notna()) &
            ((df['plan_year.valid_to'] + pd.Timedelta(days=1)).dt.day != 1)
    ),
    (
        "non-active plan",
        lambda df: df['elv_plan_status'].astype(str).str.upper() != "ACTIVE"
    ),
    (
        "non-active organization",
        lambda df: df['organization_status_type'].astype(str).str.upper() != "ACTIVE"
    ),
    (
        "short plan year",
        lambda df: (df['plan_year.valid_to'] - df['plan_year.valid_from']).dt.days < 360
    ),
    # (
    #     "moving to short plan year",
    #     lambda df: df['client_id'] == '86877zv6x'
    # ),
    (
        "`RMR` not in rmrcode",
        lambda df: ~df['rmrcode'].str.upper().str.contains('RMR', na=False)
    )
]

warning_masks = [
    # (
    #     "hra",
    #     lambda df: df['account_type.account_type'] == 'HRA'
    # ),
    (
        "no `cu_plan_id` found",
        lambda df: df['cu_plan_id'].isna()
    ),
    (
        "no `client_id` found",
        lambda df: df['client_id'].isna()
    ),
]