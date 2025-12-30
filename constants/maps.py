
ORGANIZATION_RENAME_MAP = {
    "id": "organization_id",
    "name": "organization_name",
    "status": "elv_org_status",
    "parent_id": "elv_org_parent_id",
    "parent": "elv_org_parent",
    "url": "elv_org_url",
    "external_identifier":"rmrcode"
}

ELEVATE_PLAN_RENAME_MAP = {
    "id": "elv_plan_id",
    "plan_status": "elv_plan_status",
    "parent_id": "elv_plan_parent_id",
    "url": "elv_plan_url",
    "organization_path": "plan_organization_path",
    "name.name": "elv_plan_name",
}

CLIENT_RENAME_MAP = {
    "id": "client_id",
    "name": "client_name",
    "status.status": "cu_client_status",
    "description": "cu_client_description",
    "archived": "cu_client_archived",
    "assignees": "cu_client_assignees",
    "group_assignees": "cu_client_assignees",
    "tags": "cu_client_tags",
    "url": "cu_client_url",
    "date_admin_start": "cu_client_date_admin_start",
    "elv_id": "cu_client_elv_id",
    "account_manager": "cu_client_account_manager",
    "rmr_code": "rmrcode" # omg plez switch this
}

CLICKUP_PLAN_RENAME_MAP = {
    "id": "cu_plan_id",
    "status.status": "cu_plan_status",
    "description": "cu_plan_description",
    "archived": "cu_plan_archived",
    "assignees": "cu_plan_assignees",
    "group_assignees": "cu_plan_assignees",
    "tags": "cu_plan_tags",
    "url": "cu_plan_url",
    "date_admin_start": "cu_plan_date_admin_start",
    "elv_id": "cu_plan_elv_id",
    "account_manager": "cu_plan_account_manager",
    "list.name": "cu_account_type",
}

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

COLS_TO_DROP = [
    "custom_id",
    "custom_item_id",
    "text_content",
    "description",
    "orderindex",
    "date_created",
    "date_updated",
    "date_closed",
    "date_done",
    "creator",
    "checklists",
    "priority",
    "top_level_parent",
    "due_date",
    "start_date",
    "points",
    "time_estimate",
    "dependencies",
    "linked_tasks",
    "locations",
    "team_id",
    "permission_level",
    "project",
    "folder",
    "space",
    "watchers",
    "parent"
]


ELV_TEMPLATE_IDS = {
    "PROD": {
        "HCFSA": 3,
        "DCAP": 4,
        "HRA": 5,
        "HSA": 6,
        "SPECIALTY": 53,
        "TRANSIT": 109,
        "PARKING": 110,
        "ADOPTION": 113,
        "WELLNESS": 28974,
        "LIFESTYLE": 53,
    },
    "UAT": {
        "HCFSA": 194,
        "DCAP": 195,
        "HRA": 196,
        "HSA": 197,
        "SPECIALTY": 15910,
        "TRANSIT": 25720,
        "PARKING": 25721,
        "ADOPTION": 25721,
        "WELLNESS": 25720,
    }
}

ELV_STATUS_MAP = {
    'ACTIVE':           'active',
    'DRAFT':            'review',
    'READY_FOR_SETUP':  'setup',
    # keys not present should be mapped to 'review'
}

FIELDS_TO_POP = [
    "parent_id",
    "plan_omnibus_account_id",
    "notional_payroll_account_id",
    "notional_funding_account_id",
    "plan_year",
    "service_configs",
    "prior_plan",
]

FIELDS_TO_COPY = [
    "plan_primary_config",
    "plan_coverage_config",
    "plan_account_funding_config",
]

FIELDS_TO_SET = {
    "plan_status": "DRAFT"
}