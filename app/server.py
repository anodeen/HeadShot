#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, secrets, sqlite3, time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HOST, PORT = '0.0.0.0', 4173
DB_PATH = Path(__file__).resolve().parent / 'headshot.db'
BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_TTL_DAYS, OUTPUT_TTL_DAYS, MAX_TEAM_SIZE = 7, 30, 50
PACKAGES = {
  'basic': {'name':'Basic','headshotCount':40,'priceCents':2900,'delivery':'2–3 hr'},
  'professional': {'name':'Professional','headshotCount':100,'priceCents':4900,'delivery':'1–2 hr'},
  'executive': {'name':'Executive','headshotCount':200,'priceCents':7900,'delivery':'Priority'},
}
BRANDING_PRESETS=[{'id':'linkedin','label':'LinkedIn profile','width':400,'height':400},{'id':'email','label':'Email signature','width':320,'height':320},{'id':'team','label':'Team page card','width':800,'height':600}]


def hpw(p:str)->str: return hashlib.sha256(p.encode()).hexdigest()

def db():
  c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row
  c.execute("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,email TEXT UNIQUE,password_hash TEXT,created_at INTEGER)")
  c.execute("CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id INTEGER,created_at INTEGER)")
  c.execute("CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY,user_id INTEGER,plan TEXT,team_size INTEGER DEFAULT 1,rerun_credits INTEGER DEFAULT 1,amount_cents INTEGER,payment_status TEXT,created_at INTEGER)")
  for s in ["ALTER TABLE orders ADD COLUMN team_size INTEGER DEFAULT 1","ALTER TABLE orders ADD COLUMN rerun_credits INTEGER DEFAULT 1","ALTER TABLE orders ADD COLUMN user_id INTEGER DEFAULT 1"]:
    try:c.execute(s)
    except sqlite3.OperationalError: pass
  c.execute("CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY,order_id INTEGER,source_job_id INTEGER,plan TEXT,style TEXT,background TEXT,outfit TEXT,upload_count INTEGER,created_at INTEGER)")
  try:c.execute("ALTER TABLE jobs ADD COLUMN source_job_id INTEGER")
  except sqlite3.OperationalError: pass
  c.execute("CREATE TABLE IF NOT EXISTS generated_assets(id INTEGER PRIMARY KEY,job_id INTEGER,variant TEXT,download_token TEXT,created_at INTEGER)")
  c.execute("CREATE TABLE IF NOT EXISTS support_tickets(id INTEGER PRIMARY KEY,user_id INTEGER,email TEXT,order_id INTEGER,message TEXT,created_at INTEGER)")
  c.execute("CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY,user_id INTEGER,level TEXT,message TEXT,created_at INTEGER)")
  c.commit(); return c

def pj(h):
  n=int(h.headers.get('Content-Length','0')); 
  if n<=0: return None
  try: return json.loads(h.rfile.read(n).decode())
  except json.JSONDecodeError: return None

def st(created:int):
  e=int(time.time())-created
  if e<8:return 'queued',8-e
  if e<25:return 'processing',25-e
  return 'completed',0

def amount(plan,team):
  b=PACKAGES[plan]['priceCents']; return b if team<=1 else int(b*team*0.9)

def note(c,uid,l,m): c.execute("INSERT INTO notifications(user_id,level,message,created_at) VALUES(?,?,?,?)",(uid,l,m,int(time.time())))

def assets(c,jid):
  for v in ['portrait-a','portrait-b','portrait-c','linkedin-crop']:
    c.execute("INSERT INTO generated_assets(job_id,variant,download_token,created_at) VALUES(?,?,?,?)",(jid,v,secrets.token_urlsafe(10),int(time.time())))

def auth(c,h):
  a=h.headers.get('Authorization','')
  if not a.startswith('Bearer '): return None
  t=a.split(' ',1)[1]
  return c.execute("SELECT u.id,u.email FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?",(t,)).fetchone()


class H(SimpleHTTPRequestHandler):
  def __init__(self,*a,**kw): super().__init__(*a,directory=str(BASE_DIR),**kw)
  def js(self,p,code=200):
    b=json.dumps(p).encode(); self.send_response(code); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)

  def do_GET(self):
    p=urlparse(self.path).path
    if not p.startswith('/api/'):
      return super().do_GET()
    if p=='/api/health': return self.js({'ok':True})
    if p=='/api/privacy': return self.js({'inputRetentionDays':INPUT_TTL_DAYS,'outputRetentionDays':OUTPUT_TTL_DAYS})
    if p=='/api/packages': return self.js({'packages':PACKAGES})
    if p=='/api/branding-previews': return self.js({'previews':BRANDING_PRESETS})
    with db() as c:
      u=auth(c,self)
      if p=='/api/auth/me': return self.js({'id':u['id'],'email':u['email']}) if u else self.js({'error':'Unauthorized'},401)
      if not u: return self.js({'error':'Unauthorized'},401)
      uid=u['id']
      if p=='/api/notifications':
        r=c.execute("SELECT id,level,message,created_at FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 20",(uid,)).fetchall(); return self.js({'notifications':[dict(x) for x in r]})
      if p=='/api/metrics':
        o=c.execute("SELECT COUNT(*) c FROM orders WHERE user_id=?",(uid,)).fetchone()['c']
        j=c.execute("SELECT COUNT(*) c FROM jobs j JOIN orders o ON o.id=j.order_id WHERE o.user_id=?",(uid,)).fetchone()['c']
        cp=c.execute("SELECT COUNT(*) c FROM jobs j JOIN orders o ON o.id=j.order_id WHERE o.user_id=? AND ?-j.created_at>=25",(uid,int(time.time()))).fetchone()['c']
        s=c.execute("SELECT COUNT(*) c FROM support_tickets WHERE user_id=?",(uid,)).fetchone()['c']
        return self.js({'orders':o,'jobs':j,'completedJobs':cp,'supportTickets':s})
      if p=='/api/orders':
        r=c.execute("SELECT id,plan,team_size,rerun_credits,amount_cents,payment_status,created_at FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 20",(uid,)).fetchall()
        return self.js({'orders':[{'id':x['id'],'plan':x['plan'],'teamSize':x['team_size'],'rerunCredits':x['rerun_credits'],'amountCents':x['amount_cents'],'paymentStatus':x['payment_status'],'createdAt':x['created_at']} for x in r]})
      if p=='/api/jobs':
        r=c.execute("SELECT j.* FROM jobs j JOIN orders o ON o.id=j.order_id WHERE o.user_id=? ORDER BY j.id DESC LIMIT 20",(uid,)).fetchall()
        out=[]
        for x in r:
          ss,sec=st(x['created_at']); out.append({'id':x['id'],'orderId':x['order_id'],'sourceJobId':x['source_job_id'],'plan':x['plan'],'style':x['style'],'background':x['background'],'outfit':x['outfit'],'uploadCount':x['upload_count'],'status':ss,'secondsRemaining':sec})
        return self.js({'jobs':out})
      if p.startswith('/api/jobs/') and p.endswith('/assets'):
        try: jid=int(p.split('/')[3])
        except: return self.js({'error':'Invalid job id.'},400)
        j=c.execute("SELECT j.id,j.created_at FROM jobs j JOIN orders o ON o.id=j.order_id WHERE j.id=? AND o.user_id=?",(jid,uid)).fetchone()
        if not j: return self.js({'error':'Job not found.'},404)
        if st(j['created_at'])[0] != 'completed': return self.js({'error':'Assets are available after completion.'},400)
        r=c.execute("SELECT variant,download_token FROM generated_assets WHERE job_id=?",(jid,)).fetchall()
        return self.js({'assets':[{'variant':x['variant'],'downloadUrl':f"/api/download/{x['download_token']}"} for x in r]})
      if p.startswith('/api/download/'):
        t=p.split('/')[-1]
        x=c.execute("SELECT ga.variant FROM generated_assets ga JOIN jobs j ON j.id=ga.job_id JOIN orders o ON o.id=j.order_id WHERE ga.download_token=? AND o.user_id=?",(t,uid)).fetchone()
        return self.js({'ok':True,'message':f"Mock download for {x['variant']}"}) if x else self.js({'error':'Asset not found.'},404)
      if p.startswith('/api/jobs/'):
        try: jid=int(p.split('/')[-1])
        except: return self.js({'error':'Invalid job id.'},400)
        x=c.execute("SELECT j.* FROM jobs j JOIN orders o ON o.id=j.order_id WHERE j.id=? AND o.user_id=?",(jid,uid)).fetchone()
        if not x: return self.js({'error':'Job not found.'},404)
        ss,sec=st(x['created_at']); return self.js({'id':x['id'],'orderId':x['order_id'],'sourceJobId':x['source_job_id'],'plan':x['plan'],'style':x['style'],'background':x['background'],'outfit':x['outfit'],'uploadCount':x['upload_count'],'status':ss,'secondsRemaining':sec})
    super().do_GET()

  def do_POST(self):
    p=urlparse(self.path).path; body=pj(self)
    with db() as c:
      if p=='/api/auth/register':
        if body is None: return self.js({'error':'Invalid JSON payload.'},400)
        e=str(body.get('email','')).strip().lower(); pw=str(body.get('password',''))
        if not e or len(pw)<6: return self.js({'error':'email and password(>=6) required.'},400)
        try: c.execute("INSERT INTO users(email,password_hash,created_at) VALUES(?,?,?)",(e,hpw(pw),int(time.time()))); c.commit(); return self.js({'ok':True},201)
        except sqlite3.IntegrityError: return self.js({'error':'Email already registered.'},400)
      if p=='/api/auth/login':
        if body is None: return self.js({'error':'Invalid JSON payload.'},400)
        e=str(body.get('email','')).strip().lower(); pw=str(body.get('password',''))
        u=c.execute("SELECT id,email FROM users WHERE email=? AND password_hash=?",(e,hpw(pw))).fetchone()
        if not u: return self.js({'error':'Invalid credentials.'},401)
        t=secrets.token_urlsafe(24); c.execute("INSERT INTO sessions(token,user_id,created_at) VALUES(?,?,?)",(t,u['id'],int(time.time()))); c.commit(); return self.js({'token':t,'user':{'id':u['id'],'email':u['email']}})
      if p=='/api/auth/logout':
        u=auth(c,self); 
        if not u: return self.js({'error':'Unauthorized'},401)
        t=self.headers.get('Authorization','').split(' ',1)[1]; c.execute("DELETE FROM sessions WHERE token=?",(t,)); c.commit(); return self.js({'ok':True})

      u=auth(c,self)
      if not u: return self.js({'error':'Unauthorized'},401)
      uid=u['id']

      if p=='/api/orders':
        if body is None: return self.js({'error':'Invalid JSON payload.'},400)
        plan=body.get('plan');
        if plan not in PACKAGES: return self.js({'error':'Unknown package.'},400)
        try: ts=int(body.get('teamSize',1))
        except: return self.js({'error':'teamSize must be a number.'},400)
        if ts<1 or ts>MAX_TEAM_SIZE: return self.js({'error':f'teamSize must be between 1 and {MAX_TEAM_SIZE}.'},400)
        am=amount(plan,ts); cur=c.execute("INSERT INTO orders(user_id,plan,team_size,rerun_credits,amount_cents,payment_status,created_at) VALUES(?,?,?,?,?,'paid',?)",(uid,plan,ts,1,am,int(time.time()))); note(c,uid,'info',f"Order #{cur.lastrowid} created for {plan}."); c.commit();
        return self.js({'id':cur.lastrowid,'plan':plan,'teamSize':ts,'amountCents':am,'paymentStatus':'paid','rerunCredits':1},201)

      if p=='/api/jobs':
        if body is None: return self.js({'error':'Invalid JSON payload.'},400)
        for k in ['orderId','plan','style','background','outfit','uploadCount']:
          if k not in body: return self.js({'error':'Missing required fields.'},400)
        try: oid=int(body['orderId']); up=int(body['uploadCount'])
        except: return self.js({'error':'orderId and uploadCount must be numbers.'},400)
        if up<8: return self.js({'error':'At least 8 uploads are required.'},400)
        o=c.execute("SELECT id,plan,payment_status FROM orders WHERE id=? AND user_id=?",(oid,uid)).fetchone()
        if o is None or o['payment_status']!='paid' or o['plan']!=body['plan']: return self.js({'error':'Invalid paid order for selected plan.'},400)
        cur=c.execute("INSERT INTO jobs(order_id,source_job_id,plan,style,background,outfit,upload_count,created_at) VALUES(?,NULL,?,?,?,?,?,?)",(oid,body['plan'],body['style'],body['background'],body['outfit'],up,int(time.time()))); assets(c,cur.lastrowid); note(c,uid,'info',f"Job #{cur.lastrowid} queued."); c.commit();
        return self.js({'id':cur.lastrowid,'orderId':oid,'status':'queued','secondsRemaining':8},201)

      if p=='/api/rerun':
        if body is None: return self.js({'error':'Invalid JSON payload.'},400)
        try: sj=int(body.get('jobId'))
        except: return self.js({'error':'jobId is required.'},400)
        j=c.execute("SELECT j.* FROM jobs j JOIN orders o ON o.id=j.order_id WHERE j.id=? AND o.user_id=?",(sj,uid)).fetchone()
        if not j: return self.js({'error':'Job not found.'},404)
        o=c.execute("SELECT rerun_credits FROM orders WHERE id=?",(j['order_id'],)).fetchone()
        if o is None or o['rerun_credits']<=0: return self.js({'error':'No rerun credits available.'},400)
        c.execute("UPDATE orders SET rerun_credits=rerun_credits-1 WHERE id=?",(j['order_id'],)); cur=c.execute("INSERT INTO jobs(order_id,source_job_id,plan,style,background,outfit,upload_count,created_at) VALUES(?,?,?,?,?,?,?,?)",(j['order_id'],j['id'],j['plan'],j['style'],j['background'],j['outfit'],j['upload_count'],int(time.time()))); assets(c,cur.lastrowid); note(c,uid,'warning',f"Rerun started from job #{sj} -> #{cur.lastrowid}."); c.commit()
        return self.js({'id':cur.lastrowid,'sourceJobId':sj,'status':'queued','secondsRemaining':8},201)

      if p=='/api/support':
        if body is None: return self.js({'error':'Invalid JSON payload.'},400)
        em=str(body.get('email','')).strip(); msg=str(body.get('message','')).strip(); oid=body.get('orderId')
        if not em or not msg: return self.js({'error':'email and message are required.'},400)
        try: noid=int(oid) if oid not in (None,'') else None
        except: return self.js({'error':'orderId must be numeric if provided.'},400)
        cur=c.execute("INSERT INTO support_tickets(user_id,email,order_id,message,created_at) VALUES(?,?,?,?,?)",(uid,em,noid,msg,int(time.time()))); note(c,uid,'warning',f"Support ticket #{cur.lastrowid} opened."); c.commit();
        return self.js({'id':cur.lastrowid,'message':'Support request received.'},201)

      return self.js({'error':'Route not found.'},404)

  def do_DELETE(self):
    p=urlparse(self.path).path
    with db() as c:
      u=auth(c,self)
      if not u: return self.js({'error':'Unauthorized'},401)
      uid=u['id']
      if p.startswith('/api/jobs/'):
        try: jid=int(p.split('/')[-1])
        except: return self.js({'error':'Invalid job id.'},400)
        owns=c.execute("SELECT j.id FROM jobs j JOIN orders o ON o.id=j.order_id WHERE j.id=? AND o.user_id=?",(jid,uid)).fetchone()
        if not owns: return self.js({'error':'Job not found.'},404)
        c.execute("DELETE FROM generated_assets WHERE job_id=?",(jid,)); c.execute("DELETE FROM jobs WHERE id=?",(jid,)); note(c,uid,'info',f"Job #{jid} deleted."); c.commit(); return self.js({'ok':True,'deleted':'job','id':jid})
      if p.startswith('/api/orders/'):
        try: oid=int(p.split('/')[-1])
        except: return self.js({'error':'Invalid order id.'},400)
        owns=c.execute("SELECT id FROM orders WHERE id=? AND user_id=?",(oid,uid)).fetchone()
        if not owns: return self.js({'error':'Order not found.'},404)
        rows=c.execute("SELECT id FROM jobs WHERE order_id=?",(oid,)).fetchall()
        for r in rows: c.execute("DELETE FROM generated_assets WHERE job_id=?",(r['id'],))
        c.execute("DELETE FROM jobs WHERE order_id=?",(oid,)); c.execute("DELETE FROM orders WHERE id=?",(oid,)); note(c,uid,'info',f"Order #{oid} deleted."); c.commit(); return self.js({'ok':True,'deleted':'order','id':oid})
      return self.js({'error':'Route not found.'},404)


def run():
  s=ThreadingHTTPServer((HOST,PORT),H); print(f'HeadShot server running on http://{HOST}:{PORT}'); s.serve_forever()

if __name__=='__main__': run()
