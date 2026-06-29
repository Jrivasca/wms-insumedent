from enum import Enum


class ErpProvider(str, Enum):
    DEFONTANA = "defontana"


class ErpEnvironment(str, Enum):
    TEST = "test"
    PRODUCTION = "production"


class ErpAuthMode(str, Enum):
    CLIENT_COMPANY_USER = "client_company_user"
    EMAIL_LOGIN = "email_login"


class ErpConnectionStatus(str, Enum):
    CONFIGURED = "configured"
    CONNECTED = "connected"
    ERROR = "error"
    DISABLED = "disabled"


class ErpTokenStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    ERROR = "error"
