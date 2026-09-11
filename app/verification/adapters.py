from collections.abc import Callable

import mysql.connector

from ..db import connection, fetch_one
from .contracts import IdentityRecord, LicenceRecord
from .errors import SubjectNotFound, TrustedSourceUnavailable


ConnectionFactory = Callable


class IdentitySourceAdapter:
    def __init__(self, connection_factory: ConnectionFactory = connection):
        self.connection_factory = connection_factory

    def get_identity(self, synthetic_nin: str) -> IdentityRecord:
        try:
            with self.connection_factory() as conn:
                row = fetch_one(conn, """SELECT citizen_id,date_of_birth,identity_status,record_status,
                    full_name,surname,first_name,middle_name,gender,state_of_origin,
                    state_of_residence,lga_of_residence,residential_address,
                    identity_photograph_reference AS photograph_reference
                    FROM citizens WHERE synthetic_nin=%s""", (synthetic_nin,))
        except mysql.connector.Error as exc:
            raise TrustedSourceUnavailable(type(exc).__name__) from None
        if not row or row["record_status"] != "ACTIVE":
            raise SubjectNotFound()
        return IdentityRecord(**row)


class LicenceSourceAdapter:
    def __init__(self, connection_factory: ConnectionFactory = connection):
        self.connection_factory = connection_factory

    def get_licence(self, licence_number: str) -> LicenceRecord:
        try:
            with self.connection_factory() as conn:
                row = fetch_one(conn, """SELECT licence_record_id,holder_full_name,holder_surname,
                    holder_first_name,holder_middle_name,holder_date_of_birth,holder_gender,
                    holder_photograph_reference AS photograph_reference,licence_class,
                    issue_date,expiry_date,licence_status FROM licences
                    WHERE licence_number=%s AND record_status='ACTIVE'""", (licence_number,))
        except mysql.connector.Error as exc:
            raise TrustedSourceUnavailable(type(exc).__name__) from None
        if not row:
            raise SubjectNotFound()
        return LicenceRecord(**row)
