import time,uiautomator2 as u2
t=time.time();d=u2.connect("127.0.0.1:15555");print(d.info);print("connect+info",round(time.time()-t,2))
for i in range(3):
  t=time.time();x=d.dump_hierarchy();a=time.time()-t
  t=time.time();im=d.screenshot();b=time.time()-t
  print(f"dump {a:.2f}s len={len(x)} screenshot {b:.2f}s {im.size}")
im.save("/workspace/grok-logs/u2-shot.png")
t=time.time();d.send_keys("显示");print("send_keys",round(time.time()-t,2))
