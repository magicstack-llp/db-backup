
import os
import boto3

class StorageGateway:
    def __init__(self, backup_dir=None, s3_bucket=None, s3_path=None, aws_access_key_id=None, aws_secret_access_key=None):
        self.backup_dir = backup_dir
        self.s3_bucket = s3_bucket
        self.s3_path = s3_path
        self.s3_client = None
        if s3_bucket:
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key
            )

    def store_backup(self, backup_path, db_name, s3_bucket=None, s3_key=None):
        if s3_bucket and s3_key:
            try:
                self.s3_client.upload_file(backup_path, s3_bucket, s3_key)
                print(f"Successfully uploaded {backup_path} to {s3_bucket}/{s3_key}")
            except Exception as e:
                print(f"Error uploading to S3: {e}")
        else:
            print(f"Successfully created local backup: {backup_path}")

    def cleanup_backups(self, db_name, retention_count, s3_bucket=None, s3_path=None):
        if s3_bucket and s3_path:
            self._cleanup_s3_backups(db_name, retention_count, s3_bucket, s3_path)
        else:
            self._cleanup_local_backups(db_name, retention_count)

    def _cleanup_local_backups(self, db_name, retention_count):
        db_backup_dir = os.path.join(self.backup_dir, db_name)
        if os.path.exists(db_backup_dir):
            # Prefer compressed .gz first; fall back to .sql
            backups = sorted([f for f in os.listdir(db_backup_dir) if f.endswith('.gz') or f.endswith('.sql')], reverse=True)
            if len(backups) > retention_count:
                for old_backup in backups[retention_count:]:
                    os.remove(os.path.join(db_backup_dir, old_backup))
                    print(f"Removed old local backup: {old_backup}")

    def _cleanup_s3_backups(self, db_name, retention_count, s3_bucket, s3_path):
        prefix = f"{s3_path}/{db_name}/"
        try:
            response = self.s3_client.list_objects_v2(Bucket=s3_bucket, Prefix=prefix)
            if 'Contents' in response:
                backups = sorted(response['Contents'], key=lambda obj: obj['LastModified'], reverse=True)
                if len(backups) > retention_count:
                    for old_backup in backups[retention_count:]:
                        self.s3_client.delete_object(Bucket=s3_bucket, Key=old_backup['Key'])
                        print(f"Removed old S3 backup: {old_backup['Key']}")
        except Exception as e:
            print(f"Error cleaning up S3 backups: {e}")
