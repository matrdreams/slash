import json
import os
import subprocess
import sys
import time

sys.path.insert(0,'/workspace/slash/eval'); import aosp_tasks as T
os.makedirs('results',exist_ok=True)
def airsetup(): T.sh("cmd connectivity airplane-mode disable"); T.sh("settings put global airplane_mode_on 0")
TASKS=[("search-display","open Settings and search Display",None,lambda:T._search_check("Display")),
("airplane-on","turn on airplane mode",airsetup,lambda:(T.setting("global","airplane_mode_on")=="1",f"airplane_mode_on={T.setting('global','airplane_mode_on')}")),
("alarm-730","create a 7:30 alarm in Clock",None,lambda:T._alarm_check("7:30")),
("search-zh","在设置里搜索“显示”",None,lambda:T._search_check("显示"))]
only=sys.argv[1:]
for n,p,setup,chk in TASKS:
  if only and n not in only: continue
  T.sh("am force-stop com.android.settings; am force-stop com.android.deskclock; input keyevent HOME")
  if setup: setup()
  time.sleep(2)
  out=subprocess.run(["npx","tsx","run_task.ts",n,p],capture_output=True,text=True,timeout=900).stdout
  r=json.loads([l for l in out.splitlines() if l.startswith("RESULT ")][-1][7:])
  subprocess.run(f"adb -s {T.SERIAL} exec-out screencap -p > results/{n}.png",shell=True)
  ok,why=chk(); r.update(success=ok,check=why,screenshot=os.path.abspath(f"results/{n}.png"))
  print(json.dumps(r,ensure_ascii=False),flush=True)
  open("results/results.jsonl","a").write(json.dumps(r,ensure_ascii=False)+"\n")
  if n=="airplane-on": T.sh("cmd connectivity airplane-mode disable")
