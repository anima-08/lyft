import os
import pwd
import sys
from pathlib import Path

app_user = pwd.getpwnam("app")
volume_mount = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
data_paths = [Path("/data")]

if volume_mount:
    mounted_path = Path(volume_mount)
    if mounted_path != Path("/"):
        if mounted_path not in data_paths:
            data_paths.append(mounted_path)
        database_path = mounted_path / "app.db"
    else:
        database_path = Path("/data/app.db")
    os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"

for data_path in data_paths:
    data_path.mkdir(parents=True, exist_ok=True)
    os.chown(data_path, app_user.pw_uid, app_user.pw_gid, follow_symlinks=False)
    for database_file in data_path.glob("app.db*"):
        os.chown(database_file, app_user.pw_uid, app_user.pw_gid, follow_symlinks=False)

os.setgroups([])
os.setgid(app_user.pw_gid)
os.setuid(app_user.pw_uid)
os.environ["HOME"] = app_user.pw_dir
print(
    f"Starting Lyftr API as uid={os.getuid()} database={os.environ['DATABASE_URL']}",
    flush=True,
)
os.execvp(sys.argv[1], sys.argv[1:])
