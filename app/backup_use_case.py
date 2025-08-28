
import os
import datetime
import gzip
import shutil

class BackupUseCase:
    def __init__(self, database_gateway, storage_gateway):
        self.database_gateway = database_gateway
        self.storage_gateway = storage_gateway

    def execute(self, retention_count, backup_dir=None, s3_bucket=None, s3_path=None, compress: bool = True):
        databases = self.database_gateway.list_databases()
        for db in databases:
            timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            backup_filename = f"{db.name}-{timestamp}.sql"
            if backup_dir:
                db_backup_dir = os.path.join(backup_dir, db.name)
                if not os.path.exists(db_backup_dir):
                    os.makedirs(db_backup_dir)
                backup_filepath = os.path.join(db_backup_dir, backup_filename)
                if self.database_gateway.backup_database(db.name, backup_filepath):
                    # Optional compression
                    final_path = backup_filepath
                    if compress:
                        gz_path = backup_filepath + ".gz"
                        with open(backup_filepath, "rb") as f_in, gzip.open(gz_path, "wb") as f_out:
                            shutil.copyfileobj(f_in, f_out)
                        try:
                            os.remove(backup_filepath)
                        except Exception:
                            pass
                        final_path = gz_path
                    self.storage_gateway.store_backup(final_path, db.name)
                    self.storage_gateway.cleanup_backups(db.name, retention_count)
            elif s3_bucket and s3_path:
                local_backup_path = f"/tmp/{backup_filename}"
                if self.database_gateway.backup_database(db.name, local_backup_path):
                    final_local_path = local_backup_path
                    final_key_name = backup_filename
                    if compress:
                        gz_local = local_backup_path + ".gz"
                        with open(local_backup_path, "rb") as f_in, gzip.open(gz_local, "wb") as f_out:
                            shutil.copyfileobj(f_in, f_out)
                        try:
                            os.remove(local_backup_path)
                        except Exception:
                            pass
                        final_local_path = gz_local
                        final_key_name = backup_filename + ".gz"
                    s3_key = f"{s3_path}/{db.name}/{final_key_name}"
                    self.storage_gateway.store_backup(final_local_path, db.name, s3_bucket, s3_key)
                    self.storage_gateway.cleanup_backups(db.name, retention_count, s3_bucket, s3_path)
                    try:
                        os.remove(final_local_path)
                    except Exception:
                        pass
