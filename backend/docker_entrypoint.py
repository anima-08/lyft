import os
import pwd
import sys
from pathlib import Path

app_user = pwd.getpwnam("app")
data_path = Path("/data")
data_path.mkdir(parents=True, exist_ok=True)

for path in (data_path, *data_path.rglob("*")):
    os.chown(path, app_user.pw_uid, app_user.pw_gid, follow_symlinks=False)

os.setgroups([])
os.setgid(app_user.pw_gid)
os.setuid(app_user.pw_uid)
os.execvp(sys.argv[1], sys.argv[1:])
