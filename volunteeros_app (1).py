#!/usr/bin/env python3
"""
VolunteerOS — Single-file full working app
Run:  python3 volunteeros_app.py
Open: http://localhost:5000
Demo: coord@demo.com / demo1234   or   priya@demo.com / demo1234
"""
from flask import Flask, request, jsonify, Response
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone, timedelta
import uuid, math, os, json

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///volunteeros.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET_KEY'] = 'vos-secret-2025'
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=7)
CORS(app)
db  = SQLAlchemy(app)
jwt = JWTManager(app)

def gid(): return str(uuid.uuid4())

# ══════════════════════════════════════════════════════════════════════════════
# MODELS
# ══════════════════════════════════════════════════════════════════════════════
class User(db.Model):
    __tablename__ = 'users'
    id            = db.Column(db.String, primary_key=True, default=gid)
    name          = db.Column(db.String(120), nullable=False)
    email         = db.Column(db.String(200), unique=True, nullable=False)
    password      = db.Column(db.String(200), nullable=False)
    role          = db.Column(db.String(20), default='volunteer')
    location      = db.Column(db.String(120), default='')
    bio           = db.Column(db.Text, default='')
    phone         = db.Column(db.String(30), default='')
    total_hours   = db.Column(db.Float, default=0)
    monthly_cap   = db.Column(db.Float, default=20)
    hours_this_month = db.Column(db.Float, default=0)
    reliability_score = db.Column(db.Float, default=5.0)
    avatar_color  = db.Column(db.String(10), default='#0F7B6C')
    skills        = db.relationship('VolSkill', backref='volunteer', lazy=True, cascade='all,delete-orphan')
    assignments   = db.relationship('Assignment', backref='volunteer', lazy=True)

    def to_dict(self):
        return dict(id=self.id, name=self.name, email=self.email, role=self.role,
                    location=self.location, bio=self.bio, phone=self.phone,
                    total_hours=self.total_hours, monthly_cap=self.monthly_cap,
                    hours_this_month=self.hours_this_month,
                    reliability_score=self.reliability_score,
                    avatar_color=self.avatar_color,
                    skills=[s.to_dict() for s in self.skills])

class Skill(db.Model):
    __tablename__ = 'skills'
    id            = db.Column(db.String, primary_key=True, default=gid)
    name          = db.Column(db.String(100), unique=True, nullable=False)
    category      = db.Column(db.String(60), default='Other')
    requires_cert = db.Column(db.Boolean, default=False)
    def to_dict(self): return dict(id=self.id, name=self.name, category=self.category, requires_cert=self.requires_cert)

class VolSkill(db.Model):
    __tablename__ = 'vol_skills'
    id            = db.Column(db.String, primary_key=True, default=gid)
    volunteer_id  = db.Column(db.String, db.ForeignKey('users.id'), nullable=False)
    skill_id      = db.Column(db.String, db.ForeignKey('skills.id'), nullable=False)
    proficiency   = db.Column(db.Integer, default=5)
    verified      = db.Column(db.Boolean, default=False)
    decay_factor  = db.Column(db.Float, default=1.0)
    skill         = db.relationship('Skill')
    def eff(self): return round(self.proficiency * self.decay_factor, 1)
    def to_dict(self):
        return dict(id=self.id, volunteer_id=self.volunteer_id, skill_id=self.skill_id,
                    skill_name=self.skill.name if self.skill else '', category=self.skill.category if self.skill else '',
                    proficiency=self.proficiency, verified=self.verified, effective=self.eff())

class Event(db.Model):
    __tablename__ = 'events'
    id            = db.Column(db.String, primary_key=True, default=gid)
    title         = db.Column(db.String(200), nullable=False)
    event_type    = db.Column(db.String(60), default='')
    location      = db.Column(db.String(200), default='')
    description   = db.Column(db.Text, default='')
    starts_at     = db.Column(db.DateTime)
    ends_at       = db.Column(db.DateTime)
    expected_crowd = db.Column(db.Integer, default=0)
    status        = db.Column(db.String(20), default='open')
    coordinator_id = db.Column(db.String, db.ForeignKey('users.id'))
    created_at    = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    shifts        = db.relationship('Shift', backref='event', lazy=True, cascade='all,delete-orphan')
    coordinator   = db.relationship('User', foreign_keys=[coordinator_id])

    def fill_rate(self):
        needed = sum(s.volunteers_needed for s in self.shifts)
        assigned = sum(len([a for a in s.assignments if a.status=='confirmed']) for s in self.shifts)
        return round((assigned/needed*100) if needed else 0, 1)

    def to_dict(self):
        return dict(id=self.id, title=self.title, event_type=self.event_type,
                    location=self.location, description=self.description,
                    starts_at=self.starts_at.isoformat() if self.starts_at else None,
                    ends_at=self.ends_at.isoformat() if self.ends_at else None,
                    expected_crowd=self.expected_crowd, status=self.status,
                    coordinator_id=self.coordinator_id, fill_rate=self.fill_rate(),
                    shifts=[s.to_dict() for s in self.shifts])

class Shift(db.Model):
    __tablename__ = 'shifts'
    id            = db.Column(db.String, primary_key=True, default=gid)
    event_id      = db.Column(db.String, db.ForeignKey('events.id'), nullable=False)
    role_name     = db.Column(db.String(200), nullable=False)
    volunteers_needed = db.Column(db.Integer, default=1)
    required_skill_id = db.Column(db.String, db.ForeignKey('skills.id'))
    min_proficiency   = db.Column(db.Integer, default=1)
    description   = db.Column(db.Text, default='')
    required_skill = db.relationship('Skill')
    assignments   = db.relationship('Assignment', backref='shift', lazy=True, cascade='all,delete-orphan')

    def assigned_count(self): return len([a for a in self.assignments if a.status=='confirmed'])
    def open_spots(self):     return max(0, self.volunteers_needed - self.assigned_count())

    def to_dict(self):
        return dict(id=self.id, event_id=self.event_id, role_name=self.role_name,
                    volunteers_needed=self.volunteers_needed,
                    required_skill_id=self.required_skill_id,
                    skill_name=self.required_skill.name if self.required_skill else 'No requirement',
                    min_proficiency=self.min_proficiency, description=self.description,
                    assigned_count=self.assigned_count(), open_spots=self.open_spots(),
                    assignments=[a.to_dict() for a in self.assignments])

class Assignment(db.Model):
    __tablename__ = 'assignments'
    id           = db.Column(db.String, primary_key=True, default=gid)
    shift_id     = db.Column(db.String, db.ForeignKey('shifts.id'), nullable=False)
    volunteer_id = db.Column(db.String, db.ForeignKey('users.id'), nullable=False)
    match_score  = db.Column(db.Float, default=0)
    status       = db.Column(db.String(20), default='pending')
    assigned_at  = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    notes        = db.Column(db.Text, default='')
    def to_dict(self):
        return dict(id=self.id, shift_id=self.shift_id, volunteer_id=self.volunteer_id,
                    volunteer_name=self.volunteer.name if self.volunteer else '',
                    match_score=self.match_score, status=self.status,
                    assigned_at=self.assigned_at.isoformat() if self.assigned_at else None)

# ══════════════════════════════════════════════════════════════════════════════
# MATCHING ENGINE
# ══════════════════════════════════════════════════════════════════════════════
def proximity_score(v_loc, e_loc):
    if not v_loc or not e_loc: return 0.5
    vp = set(v_loc.lower().replace(',',' ').split())
    ep = set(e_loc.lower().replace(',',' ').split())
    if vp == ep: return 1.0
    return 0.7 if vp & ep else 0.3

def score_vol_shift(volunteer, shift):
    skill_fit = 0.5
    if shift.required_skill_id:
        vs = VolSkill.query.filter_by(volunteer_id=volunteer.id, skill_id=shift.required_skill_id).first()
        if not vs: return 0.0
        eff = vs.eff()
        if eff < shift.min_proficiency: return 0.0
        skill_fit = min(eff/10.0, 1.0)
    reliability   = min((volunteer.reliability_score or 0)/5.0, 1.0)
    cap           = volunteer.monthly_cap or 20
    used          = volunteer.hours_this_month or 0
    burnout       = max(0, (cap-used)/cap)
    prox          = proximity_score(volunteer.location, shift.event.location if shift.event else '')
    return round((skill_fit*0.40 + reliability*0.30 + prox*0.20 + burnout*0.10)*100, 1)

def get_candidates(shift, limit=10):
    assigned_ids = {a.volunteer_id for a in shift.assignments if a.status in ('pending','confirmed')}
    scored = []
    for v in User.query.filter_by(role='volunteer').all():
        if v.id in assigned_ids: continue
        s = score_vol_shift(v, shift)
        if s > 0: scored.append((v, s))
    scored.sort(key=lambda x: -x[1])
    return scored[:limit]

TEMPLATES = {
    'flood':  [('First-aid coordinator','First Aid',250,2,7),('Search & rescue','Physical Fitness',400,2,5),
               ('Language coordinator','Regional Language',600,1,6),('Logistics lead','Crowd Management',350,2,6),
               ('Mental health','Counselling',800,1,6),('Data recorder','Data Entry',500,1,4)],
    'medical':[('Medical assistant','First Aid',150,3,8),('Patient registration','Data Entry',200,2,4),
               ('Queue management','Crowd Management',300,2,5),('Translator','Regional Language',400,1,7)],
    'food':   [('Food prep','',100,3,1),('Distribution coordinator','Crowd Management',250,2,5),
               ('Record keeper','Data Entry',400,1,4)],
    'digital':[('Digital trainer','Tech Literacy',30,2,7),('Teaching assistant','Tech Literacy',20,2,5),
               ('Logistics','Crowd Management',100,1,4)],
    'environment':[('Team lead','',80,2,1),('Volunteer coordinator','Crowd Management',150,2,4),
                   ('Data recorder','Data Entry',200,1,3)],
}

def predict_shifts(event_type, crowd):
    tmpl = TEMPLATES.get(event_type, TEMPLATES['food'])
    return [{'role':r,'skill':sk,'count':max(mn,math.ceil(crowd/per)),'min_proficiency':mp}
            for r,sk,per,mn,mp in tmpl]

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def err(msg,code=400): return jsonify(error=msg), code
def ok(data,code=200): return jsonify(data), code
def cu(): return User.query.get(get_jwt_identity())

# ══════════════════════════════════════════════════════════════════════════════
# AUTH ROUTES
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/api/auth/register', methods=['POST'])
def register():
    d = request.json or {}
    if not d.get('email') or not d.get('password') or not d.get('name'): return err('name,email,password required')
    if User.query.filter_by(email=d['email']).first(): return err('Email already registered')
    colors = ['#0F7B6C','#5B4FCF','#C47A1A','#C94D2F','#3A7D3A']
    u = User(name=d['name'], email=d['email'], password=generate_password_hash(d['password']),
             role=d.get('role','volunteer'), location=d.get('location',''),
             avatar_color=colors[hash(d['email'])%len(colors)])
    db.session.add(u); db.session.commit()
    return ok({'token':create_access_token(identity=u.id),'user':u.to_dict()},201)

@app.route('/api/auth/login', methods=['POST'])
def login():
    d = request.json or {}
    u = User.query.filter_by(email=d.get('email','')).first()
    if not u or not check_password_hash(u.password, d.get('password','')): return err('Invalid credentials',401)
    return ok({'token':create_access_token(identity=u.id),'user':u.to_dict()})

@app.route('/api/auth/me')
@jwt_required()
def me(): return ok(cu().to_dict())

# ══════════════════════════════════════════════════════════════════════════════
# VOLUNTEER ROUTES
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/api/volunteers')
@jwt_required()
def list_vols():
    q = User.query.filter_by(role='volunteer')
    if request.args.get('location'): q = q.filter(User.location.ilike(f"%{request.args['location']}%"))
    return ok([v.to_dict() for v in q.all()])

@app.route('/api/volunteers/<vid>')
@jwt_required()
def get_vol(vid): return ok(User.query.get_or_404(vid).to_dict())

@app.route('/api/volunteers/<vid>', methods=['PUT'])
@jwt_required()
def update_vol(vid):
    u = cu()
    if u.id != vid and u.role != 'coordinator': return err('Forbidden',403)
    v = User.query.get_or_404(vid); d = request.json or {}
    for f in ['name','location','bio','phone','monthly_cap']:
        if f in d: setattr(v,f,d[f])
    db.session.commit(); return ok(v.to_dict())

@app.route('/api/volunteers/<vid>/skills', methods=['POST'])
@jwt_required()
def add_skill_to_vol(vid):
    u = cu()
    if u.id != vid and u.role != 'coordinator': return err('Forbidden',403)
    d = request.json or {}
    sk = Skill.query.filter(Skill.name.ilike(d.get('skill_name',''))).first()
    if not sk: return err('Skill not found')
    ex = VolSkill.query.filter_by(volunteer_id=vid, skill_id=sk.id).first()
    if ex:
        ex.proficiency = d.get('proficiency', ex.proficiency)
        ex.verified    = d.get('verified', ex.verified)
        db.session.commit(); return ok(ex.to_dict())
    vs = VolSkill(volunteer_id=vid, skill_id=sk.id,
                  proficiency=d.get('proficiency',5), verified=d.get('verified',False))
    db.session.add(vs); db.session.commit(); return ok(vs.to_dict(),201)

@app.route('/api/volunteers/<vid>/skills/<sid>', methods=['DELETE'])
@jwt_required()
def del_skill(vid, sid):
    u = cu()
    if u.id != vid and u.role != 'coordinator': return err('Forbidden',403)
    vs = VolSkill.query.filter_by(volunteer_id=vid, id=sid).first_or_404()
    db.session.delete(vs); db.session.commit(); return ok({'deleted':True})

# ══════════════════════════════════════════════════════════════════════════════
# SKILLS MASTER
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/api/skills')
@jwt_required()
def list_skills(): return ok([s.to_dict() for s in Skill.query.all()])

# ══════════════════════════════════════════════════════════════════════════════
# EVENT ROUTES
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/api/events')
@jwt_required()
def list_events():
    q = Event.query
    if request.args.get('status'): q = q.filter_by(status=request.args['status'])
    return ok([e.to_dict() for e in q.order_by(Event.starts_at).all()])

@app.route('/api/events', methods=['POST'])
@jwt_required()
def create_event():
    d = request.json or {}
    if not d.get('title'): return err('title required')
    u = cu()
    e = Event(title=d['title'], event_type=d.get('event_type',''),
              location=d.get('location',''), description=d.get('description',''),
              expected_crowd=int(d.get('expected_crowd',0)), status=d.get('status','open'),
              coordinator_id=u.id,
              starts_at=datetime.fromisoformat(d['starts_at']) if d.get('starts_at') else None,
              ends_at=datetime.fromisoformat(d['ends_at']) if d.get('ends_at') else None)
    db.session.add(e); db.session.flush()
    shifts_data = d.get('shifts') or predict_shifts(e.event_type, e.expected_crowd)
    for sd in shifts_data:
        sk = Skill.query.filter(Skill.name.ilike(sd.get('skill') or '')).first() if sd.get('skill') else None
        s  = Shift(event_id=e.id, role_name=sd.get('role') or sd.get('role_name',''),
                   volunteers_needed=sd.get('count') or sd.get('volunteers_needed',1),
                   required_skill_id=sk.id if sk else None,
                   min_proficiency=sd.get('min_proficiency',1))
        db.session.add(s)
    db.session.commit(); return ok(e.to_dict(),201)

@app.route('/api/events/<eid>')
@jwt_required()
def get_event(eid): return ok(Event.query.get_or_404(eid).to_dict())

@app.route('/api/events/<eid>', methods=['PUT'])
@jwt_required()
def update_event(eid):
    e = Event.query.get_or_404(eid); d = request.json or {}
    for f in ['title','event_type','location','description','expected_crowd','status']:
        if f in d: setattr(e,f,d[f])
    if d.get('starts_at'): e.starts_at = datetime.fromisoformat(d['starts_at'])
    db.session.commit(); return ok(e.to_dict())

@app.route('/api/events/<eid>', methods=['DELETE'])
@jwt_required()
def delete_event(eid):
    e = Event.query.get_or_404(eid); db.session.delete(e); db.session.commit()
    return ok({'deleted':True})

@app.route('/api/events/predict-shifts', methods=['POST'])
@jwt_required()
def predict_api():
    d = request.json or {}
    return ok({'plan': predict_shifts(d.get('event_type','food'), int(d.get('crowd',100)))})

# ══════════════════════════════════════════════════════════════════════════════
# SHIFT ROUTES
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/api/events/<eid>/shifts', methods=['POST'])
@jwt_required()
def add_shift(eid):
    e = Event.query.get_or_404(eid); d = request.json or {}
    sk = Skill.query.filter(Skill.name.ilike(d.get('skill_name',''))).first() if d.get('skill_name') else None
    s  = Shift(event_id=e.id, role_name=d['role_name'],
               volunteers_needed=d.get('volunteers_needed',1),
               required_skill_id=sk.id if sk else None,
               min_proficiency=d.get('min_proficiency',1))
    db.session.add(s); db.session.commit(); return ok(s.to_dict(),201)

@app.route('/api/shifts/<sid>', methods=['PUT'])
@jwt_required()
def update_shift(sid):
    s = Shift.query.get_or_404(sid); d = request.json or {}
    for f in ['role_name','volunteers_needed','min_proficiency','description']:
        if f in d: setattr(s,f,d[f])
    db.session.commit(); return ok(s.to_dict())

@app.route('/api/shifts/<sid>', methods=['DELETE'])
@jwt_required()
def delete_shift(sid):
    s = Shift.query.get_or_404(sid); db.session.delete(s); db.session.commit()
    return ok({'deleted':True})

# ══════════════════════════════════════════════════════════════════════════════
# MATCHING & ASSIGNMENT ROUTES
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/api/shifts/<sid>/candidates')
@jwt_required()
def candidates(sid):
    s = Shift.query.get_or_404(sid)
    result = []
    for v, score in get_candidates(s):
        vd = v.to_dict(); vd['match_score'] = score; result.append(vd)
    return ok(result)

@app.route('/api/shifts/<sid>/assign', methods=['POST'])
@jwt_required()
def assign(sid):
    s = Shift.query.get_or_404(sid); d = request.json or {}
    vid = d.get('volunteer_id')
    if not vid: return err('volunteer_id required')
    v   = User.query.get_or_404(vid)
    ex  = Assignment.query.filter_by(shift_id=sid, volunteer_id=vid).first()
    if ex: ex.status='confirmed'; db.session.commit(); return ok(ex.to_dict())
    a = Assignment(shift_id=sid, volunteer_id=vid, match_score=score_vol_shift(v,s), status='confirmed')
    db.session.add(a); db.session.commit(); return ok(a.to_dict(),201)

@app.route('/api/events/<eid>/auto-assign', methods=['POST'])
@jwt_required()
def auto_assign(eid):
    e = Event.query.get_or_404(eid)
    results = {}
    for shift in e.shifts:
        added = []
        for v, score in get_candidates(shift, limit=shift.open_spots()):
            if len(added) >= shift.open_spots(): break
            a = Assignment(shift_id=shift.id, volunteer_id=v.id, match_score=score, status='confirmed')
            db.session.add(a); added.append({'name':v.name,'score':score})
        results[shift.id] = {'role':shift.role_name,'assigned':added}
    db.session.commit(); return ok({'results':results})

@app.route('/api/assignments/<aid>', methods=['PUT'])
@jwt_required()
def update_assignment(aid):
    a = Assignment.query.get_or_404(aid); d = request.json or {}
    if 'status' in d: a.status=d['status']
    if 'notes'  in d: a.notes=d['notes']
    db.session.commit(); return ok(a.to_dict())

# ══════════════════════════════════════════════════════════════════════════════
# VOLUNTEER FEED
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/api/my/feed')
@jwt_required()
def my_feed():
    v = cu()
    if v.role != 'volunteer': return err('Volunteers only',403)
    assigned_shift_ids = {a.shift_id for a in Assignment.query.filter_by(volunteer_id=v.id).all()
                          if a.status in ('confirmed','pending')}
    scored = []
    for event in Event.query.filter_by(status='open').all():
        for shift in event.shifts:
            if shift.id in assigned_shift_ids or shift.open_spots() <= 0: continue
            s = score_vol_shift(v, shift)
            if s > 0:
                scored.append({'shift':shift.to_dict(), 'match_score':s,
                               'event':dict(id=event.id,title=event.title,location=event.location,
                                            event_type=event.event_type,
                                            starts_at=event.starts_at.isoformat() if event.starts_at else None)})
    scored.sort(key=lambda x: -x['match_score']); return ok(scored)

@app.route('/api/my/assignments')
@jwt_required()
def my_assignments():
    v = cu()
    result = []
    for a in Assignment.query.filter_by(volunteer_id=v.id).all():
        d = a.to_dict()
        d['shift'] = a.shift.to_dict() if a.shift else {}
        d['event'] = a.shift.event.to_dict() if a.shift and a.shift.event else {}
        result.append(d)
    return ok(result)

@app.route('/api/my/respond', methods=['POST'])
@jwt_required()
def respond():
    v = cu(); d = request.json or {}
    shift_id = d.get('shift_id'); action = d.get('action')
    if action not in ('accept','decline'): return err('action must be accept|decline')
    s  = Shift.query.get_or_404(shift_id)
    ex = Assignment.query.filter_by(shift_id=shift_id, volunteer_id=v.id).first()
    if action == 'accept':
        if s.open_spots() <= 0 and not ex: return err('No spots left')
        if ex: ex.status='confirmed'
        else:
            a = Assignment(shift_id=shift_id, volunteer_id=v.id,
                           match_score=score_vol_shift(v,s), status='confirmed')
            db.session.add(a)
    else:
        if ex: ex.status='declined'
        else:
            a = Assignment(shift_id=shift_id, volunteer_id=v.id, match_score=0, status='declined')
            db.session.add(a)
    db.session.commit(); return ok({'status':action})

# ══════════════════════════════════════════════════════════════════════════════
# ANALYTICS
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/api/analytics/overview')
@jwt_required()
def analytics_overview():
    vols   = User.query.filter_by(role='volunteer').count()
    events = Event.query.all()
    frs    = [e.fill_rate() for e in events if e.shifts]
    burnout = User.query.filter(User.role=='volunteer',
                                User.hours_this_month >= User.monthly_cap * 0.8).count()
    total_assign = Assignment.query.count()
    no_shows     = Assignment.query.filter_by(status='no_show').count()
    return ok(dict(total_volunteers=vols, total_events=len(events),
                   open_events=Event.query.filter_by(status='open').count(),
                   avg_fill_rate=round(sum(frs)/len(frs),1) if frs else 0,
                   total_hours=round(db.session.query(db.func.sum(User.total_hours)).scalar() or 0,1),
                   burnout_flags=burnout,
                   no_show_rate=round(no_shows/total_assign*100,1) if total_assign else 0))

@app.route('/api/analytics/skills-gap')
@jwt_required()
def skills_gap():
    demand = {}
    for e in Event.query.filter_by(status='open').all():
        for s in e.shifts:
            if s.required_skill_id:
                demand[s.required_skill_id] = demand.get(s.required_skill_id,0) + s.open_spots()
    result = []
    for sid, shortage in sorted(demand.items(), key=lambda x:-x[1])[:8]:
        sk = Skill.query.get(sid)
        if sk:
            supply = VolSkill.query.filter_by(skill_id=sid).count()
            result.append(dict(skill=sk.name, shortage=shortage, supply=supply))
    return ok(result)

@app.route('/api/analytics/top-volunteers')
@jwt_required()
def top_vols():
    return ok([v.to_dict() for v in User.query.filter_by(role='volunteer').order_by(User.total_hours.desc()).limit(10).all()])

# ══════════════════════════════════════════════════════════════════════════════
# SEED DATA
# ══════════════════════════════════════════════════════════════════════════════
def seed():
    if User.query.count() > 0: return
    skills_data = [
        ('First Aid','Medical',True),('Counselling','Medical',True),('Physical Fitness','Medical',False),
        ('Crowd Management','Logistics',False),('Driving','Logistics',False),
        ('Regional Language','Language',False),('Tamil','Language',False),
        ('Hindi','Language',False),('Kannada','Language',False),
        ('Data Entry','Digital',False),('Tech Literacy','Digital',False),('Social Media','Digital',False),
    ]
    sm = {}
    for name,cat,cert in skills_data:
        s = Skill(name=name,category=cat,requires_cert=cert); db.session.add(s); sm[name] = s
    db.session.flush()
    coord = User(name='Nandini Krishnan',email='coord@demo.com',
                 password=generate_password_hash('demo1234'),role='coordinator',
                 location='Bengaluru',avatar_color='#5B4FCF')
    db.session.add(coord)
    vols = [
        ('Priya Menon','priya@demo.com','Bengaluru',42,6,4.9,'#0F7B6C',
         [('First Aid',9,True),('Tamil',10,True),('Crowd Management',7,False)]),
        ('Arjun Kumar','arjun@demo.com','Chennai',38,9,4.7,'#5B4FCF',
         [('Crowd Management',8,False),('First Aid',6,False),('Tamil',8,True)]),
        ('Sneha Patel','sneha@demo.com','Mumbai',29,14,4.6,'#C47A1A',
         [('Data Entry',9,False),('Tech Literacy',8,False)]),
        ('Rahul Anand','rahul@demo.com','Bengaluru',51,18,4.2,'#C94D2F',
         [('Physical Fitness',9,False),('Crowd Management',7,False),('Driving',8,False)]),
        ('Meena Rao','meena@demo.com','Pune',44,17,4.8,'#3A7D3A',
         [('First Aid',8,True),('Counselling',7,True),('Kannada',9,True)]),
        ('Vikram Shah','vikram@demo.com','Mumbai',22,5,4.5,'#0F7B6C',
         [('First Aid',7,False)]),
        ('Divya Sharma','divya@demo.com','Pune',18,4,4.3,'#5B4FCF',
         [('First Aid',6,False),('Data Entry',7,False)]),
        ('Kiran Nair','kiran@demo.com','Bengaluru',33,8,4.6,'#C47A1A',
         [('Tech Literacy',9,False),('Social Media',8,False)]),
    ]
    for name,email,loc,total,month,rel,color,skls in vols:
        v = User(name=name,email=email,password=generate_password_hash('demo1234'),
                 role='volunteer',location=loc,total_hours=total,hours_this_month=month,
                 reliability_score=rel,avatar_color=color)
        db.session.add(v); db.session.flush()
        for sn,prof,ver in skls:
            sk = sm.get(sn)
            if sk: db.session.add(VolSkill(volunteer_id=v.id,skill_id=sk.id,proficiency=prof,verified=ver))
    db.session.flush()
    now = datetime.now(timezone.utc)
    events = [('Flood Relief — Coastal TN','flood','Chennai, Tamil Nadu',2400,'open',3),
              ('Food Drive — Dharavi','food','Mumbai, Maharashtra',800,'open',6),
              ('Medical Camp — Pune','medical','Pune, Maharashtra',1100,'open',10),
              ('Digital Literacy — Bhopal','digital','Bhopal, Madhya Pradesh',300,'open',13),
              ('Tree Plantation — Bengaluru','environment','Bengaluru, Karnataka',600,'open',15)]
    for title,etype,loc,crowd,status,days in events:
        e = Event(title=title,event_type=etype,location=loc,expected_crowd=crowd,status=status,
                  coordinator_id=coord.id,starts_at=now+timedelta(days=days),ends_at=now+timedelta(days=days,hours=8))
        db.session.add(e); db.session.flush()
        for pd in predict_shifts(etype,crowd):
            sk = Skill.query.filter(Skill.name.ilike(pd['skill'] or '')).first() if pd['skill'] else None
            db.session.add(Shift(event_id=e.id,role_name=pd['role'],volunteers_needed=pd['count'],
                                 required_skill_id=sk.id if sk else None,min_proficiency=pd['min_proficiency']))
    db.session.commit()
    print("\n✅ Seed complete!\n   Coordinator: coord@demo.com / demo1234\n   Volunteer:   priya@demo.com / demo1234\n")

# ══════════════════════════════════════════════════════════════════════════════
# FRONTEND HTML (served at /)
# ══════════════════════════════════════════════════════════════════════════════
FRONTEND = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>VolunteerOS</title>
<style>
:root{--bg:#F5F4F0;--surface:#fff;--s2:#F0EFE9;--border:#E2E0D8;--text:#1A1916;--t2:#6B6960;--t3:#A8A69E;
  --teal:#0F7B6C;--tl:#E0F5F1;--amber:#C47A1A;--al:#FDF3E3;--purple:#5B4FCF;--pl:#EEEDFE;
  --coral:#C94D2F;--cl:#FAECEA;--green:#3A7D3A;--gl:#E8F5E8;--r:12px;--rs:8px;}
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text);font-size:14px;min-height:100vh;}

/* NAV */
.nav{background:var(--surface);border-bottom:1px solid var(--border);padding:0 20px;height:52px;display:flex;align-items:center;gap:0;position:sticky;top:0;z-index:100;}
.logo{font-size:17px;font-weight:700;color:var(--teal);margin-right:28px;letter-spacing:-0.5px;}
.nav-tabs{display:flex;gap:2px;flex:1;}
.nt{padding:6px 13px;border-radius:8px;font-size:13px;font-weight:500;color:var(--t2);cursor:pointer;border:none;background:transparent;transition:all .15s;}
.nt:hover{background:var(--s2);color:var(--text);}
.nt.active{background:var(--tl);color:var(--teal);}
.nav-right{margin-left:auto;display:flex;align-items:center;gap:10px;}
.avatar{width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;cursor:pointer;}

/* LAYOUT */
.page{display:none;padding:22px;max-width:1300px;margin:0 auto;animation:fadeUp .2s ease;}
.page.active{display:block;}
@keyframes fadeUp{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}

/* CARDS */
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:20px;box-shadow:0 1px 3px rgba(0,0,0,.06);}
.card-title{font-size:12px;font-weight:600;color:var(--t2);text-transform:uppercase;letter-spacing:.06em;margin-bottom:14px;display:flex;align-items:center;justify-content:space-between;}
.card-action{font-size:12px;font-weight:500;color:var(--teal);cursor:pointer;text-transform:none;letter-spacing:0;}

/* STATS */
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px;}
.stat{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:16px;}
.stat-label{font-size:11px;color:var(--t2);font-weight:500;margin-bottom:5px;}
.stat-val{font-size:26px;font-weight:700;letter-spacing:-1px;}
.stat-sub{font-size:11px;color:var(--t3);margin-top:3px;}

/* GRIDS */
.g2{display:grid;grid-template-columns:1.4fr 1fr;gap:18px;}
.g3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:18px;}
.gap{height:18px;}

/* BADGE */
.badge{display:inline-flex;align-items:center;font-size:11px;font-weight:500;padding:3px 8px;border-radius:20px;white-space:nowrap;}
.bt{background:var(--tl);color:var(--teal);}
.ba{background:var(--al);color:var(--amber);}
.bc{background:var(--cl);color:var(--coral);}
.bg2{background:var(--gl);color:var(--green);}
.bp{background:var(--pl);color:var(--purple);}
.bx{background:var(--s2);color:var(--t2);}

/* BUTTONS */
.btn{display:inline-flex;align-items:center;gap:6px;padding:8px 16px;border-radius:var(--rs);font-size:13px;font-weight:500;cursor:pointer;border:none;font-family:inherit;transition:all .15s;}
.btn-p{background:var(--teal);color:#fff;} .btn-p:hover{background:#0a6b5d;}
.btn-o{background:transparent;color:var(--teal);border:1px solid var(--teal);} .btn-o:hover{background:var(--tl);}
.btn-g{background:var(--s2);color:var(--text);border:1px solid var(--border);}
.btn-d{background:var(--cl);color:var(--coral);}
.btn:disabled{opacity:.5;cursor:not-allowed;}

/* FORM */
.form-row{margin-bottom:13px;}
.form-label{font-size:12px;font-weight:500;color:var(--t2);margin-bottom:4px;}
.form-input,.form-select{width:100%;padding:8px 11px;border:1px solid var(--border);border-radius:var(--rs);font-size:13px;font-family:inherit;background:var(--surface);color:var(--text);outline:none;}
.form-input:focus,.form-select:focus{border-color:var(--teal);}
.form-grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px;}

/* VOLUNTEER ROW */
.vrow{display:flex;align-items:center;gap:10px;padding:9px 0;border-bottom:1px solid var(--border);}
.vrow:last-child{border-bottom:none;}
.vav{width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;flex-shrink:0;}
.vinfo{flex:1;min-width:0;}
.vname{font-size:13px;font-weight:500;}
.vmeta{font-size:11px;color:var(--t3);margin-top:1px;}

/* SHIFT CARD (volunteer) */
.sc{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:10px;transition:border-color .15s;}
.sc:hover{border-color:var(--teal);}
.sc-org{font-size:11px;color:var(--t3);font-weight:500;text-transform:uppercase;letter-spacing:.04em;}
.sc-title{font-size:14px;font-weight:600;margin-top:2px;}
.sc-tags{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px;}
.sc-tag{font-size:11px;color:var(--t2);background:var(--s2);padding:3px 8px;border-radius:20px;}
.sc-foot{display:flex;align-items:center;justify-content:space-between;margin-top:12px;}
.ms-badge{font-size:11px;font-weight:600;color:var(--teal);background:var(--tl);padding:3px 8px;border-radius:20px;}
.sc-btns{display:flex;gap:6px;}

/* BAR */
.bar-bg{height:5px;background:var(--s2);border-radius:5px;}
.bar-fill{height:5px;border-radius:5px;transition:width .4s;}

/* TABLE */
table{width:100%;border-collapse:collapse;}
th{text-align:left;font-size:11px;font-weight:600;color:var(--t3);text-transform:uppercase;letter-spacing:.05em;padding:0 8px 10px;border-bottom:1px solid var(--border);}
td{padding:10px 8px;border-bottom:1px solid var(--border);font-size:13px;vertical-align:middle;}
tr:last-child td{border-bottom:none;}
tr:hover td{background:var(--s2);}

/* PHONE */
.mobile-wrap{display:flex;gap:32px;align-items:flex-start;justify-content:center;}
.phone{width:340px;flex-shrink:0;background:#111;border-radius:36px;padding:12px;box-shadow:0 20px 60px rgba(0,0,0,.3);}
.phone-screen{background:var(--bg);border-radius:26px;overflow:hidden;height:680px;display:flex;flex-direction:column;}
.ph-bar{background:var(--surface);padding:10px 16px 6px;display:flex;justify-content:space-between;font-size:11px;font-weight:700;}
.ph-hdr{background:var(--surface);padding:12px 16px;border-bottom:1px solid var(--border);}
.ph-hdr-t{font-size:20px;font-weight:700;letter-spacing:-0.5px;}
.ph-hdr-s{font-size:12px;color:var(--t2);margin-top:2px;}
.ph-body{flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:9px;}
.ph-body::-webkit-scrollbar{display:none;}
.ph-nav{background:var(--surface);border-top:1px solid var(--border);padding:8px 0 10px;display:flex;justify-content:space-around;}
.ph-ni{display:flex;flex-direction:column;align-items:center;gap:3px;font-size:10px;color:var(--t3);cursor:pointer;padding:4px 12px;border-radius:8px;}
.ph-ni.active{color:var(--teal);}
.ph-icon{font-size:18px;}

/* Impact card */
.impact{background:var(--teal);border-radius:var(--r);padding:14px;color:#fff;}
.impact-num{font-size:28px;font-weight:700;letter-spacing:-1px;}
.impact-lbl{font-size:12px;opacity:.8;margin-top:2px;}
.impact-sub{font-size:11px;opacity:.65;margin-top:8px;}

/* Streak */
.streak-row{display:flex;gap:6px;margin-top:8px;}
.sd{width:32px;height:32px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:600;}
.sd-done{background:var(--teal);color:#fff;}
.sd-today{background:var(--al);color:var(--amber);border:2px solid var(--amber);}
.sd-empty{background:var(--s2);color:var(--t3);}

/* Right panel */
.right-panel{max-width:380px;display:flex;flex-direction:column;gap:20px;}
.rp-title{font-size:14px;font-weight:600;margin-bottom:4px;}
.rp-body{font-size:13px;color:var(--t2);line-height:1.5;}

/* AUTH */
.auth-wrap{min-height:100vh;display:flex;align-items:center;justify-content:center;background:var(--bg);}
.auth-box{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:32px;width:100%;max-width:380px;box-shadow:0 4px 20px rgba(0,0,0,.08);}
.auth-logo{font-size:22px;font-weight:700;color:var(--teal);margin-bottom:4px;}
.auth-sub{font-size:13px;color:var(--t2);margin-bottom:24px;}
.auth-switch{text-align:center;margin-top:16px;font-size:13px;color:var(--t2);}
.auth-switch span{color:var(--teal);cursor:pointer;font-weight:500;}
.err-msg{background:var(--cl);color:var(--coral);padding:8px 12px;border-radius:var(--rs);font-size:13px;margin-bottom:12px;}

/* Loading */
.loading{text-align:center;padding:40px;color:var(--t3);font-size:13px;}
.dot{display:inline-block;animation:pulse 1.2s ease infinite;}
.dot:nth-child(2){animation-delay:.2s;}.dot:nth-child(3){animation-delay:.4s;}
@keyframes pulse{0%,80%,100%{opacity:0}40%{opacity:1}}

/* Notification dot */
.ndot{width:7px;height:7px;border-radius:50%;background:var(--coral);display:inline-block;margin-left:4px;vertical-align:middle;}

/* skill pill */
.skill-pill{display:inline-flex;align-items:center;background:var(--s2);border:1px solid var(--border);border-radius:20px;padding:5px 10px;font-size:12px;font-weight:500;margin:3px;}

/* tabs */
.inner-tabs{display:flex;gap:2px;margin-bottom:16px;border-bottom:1px solid var(--border);}
.it{padding:8px 14px;font-size:13px;font-weight:500;color:var(--t2);cursor:pointer;border:none;background:transparent;border-bottom:2px solid transparent;margin-bottom:-1px;transition:all .15s;font-family:inherit;}
.it.active{color:var(--teal);border-bottom-color:var(--teal);}

.empty{text-align:center;padding:40px;color:var(--t3);font-size:13px;}
.gap-row{display:flex;align-items:center;gap:10px;margin-bottom:10px;}
.gap-name{font-size:13px;font-weight:500;width:150px;flex-shrink:0;}
.gap-bar-bg{flex:1;height:6px;background:var(--s2);border-radius:6px;}
.gap-bar-fill{height:6px;border-radius:6px;}
.gap-count{font-size:12px;font-weight:600;color:var(--t2);width:30px;text-align:right;}

.toast{position:fixed;bottom:24px;right:24px;background:#1a1916;color:#fff;padding:12px 18px;border-radius:var(--rs);font-size:13px;font-weight:500;z-index:999;animation:slideUp .2s ease;box-shadow:0 4px 20px rgba(0,0,0,.2);}
@keyframes slideUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
</style>
</head>
<body>

<!-- AUTH SCREEN -->
<div id="auth-screen" class="auth-wrap">
  <div class="auth-box">
    <div class="auth-logo">◉ VolunteerOS</div>
    <div class="auth-sub">Smarter volunteer coordination</div>
    <div id="auth-err" class="err-msg" style="display:none"></div>
    <div id="auth-name-row" class="form-row" style="display:none">
      <div class="form-label">Full name</div>
      <input class="form-input" id="auth-name" placeholder="Your name">
    </div>
    <div id="auth-role-row" class="form-row" style="display:none">
      <div class="form-label">I am a…</div>
      <select class="form-select" id="auth-role">
        <option value="volunteer">Volunteer</option>
        <option value="coordinator">Coordinator / NGO</option>
      </select>
    </div>
    <div id="auth-loc-row" class="form-row" style="display:none">
      <div class="form-label">City</div>
      <input class="form-input" id="auth-loc" placeholder="e.g. Bengaluru">
    </div>
    <div class="form-row">
      <div class="form-label">Email</div>
      <input class="form-input" id="auth-email" placeholder="you@example.com" type="email">
    </div>
    <div class="form-row">
      <div class="form-label">Password</div>
      <input class="form-input" id="auth-password" placeholder="••••••••" type="password">
    </div>
    <button class="btn btn-p" id="auth-btn" style="width:100%" onclick="doAuth()">Sign in</button>
    <div class="auth-switch">
      <span id="auth-toggle-link" onclick="toggleAuthMode()">Don't have an account? Sign up</span>
    </div>
    <div style="margin-top:16px;padding:12px;background:var(--tl);border-radius:var(--rs);font-size:12px;color:var(--teal)">
      <strong>Demo:</strong> coord@demo.com / demo1234 &nbsp;|&nbsp; priya@demo.com / demo1234
    </div>
  </div>
</div>

<!-- MAIN APP (hidden until logged in) -->
<div id="main-app" style="display:none">
  <nav class="nav">
    <div class="logo">◉ VolunteerOS</div>
    <div class="nav-tabs" id="coord-tabs" style="display:none">
      <button class="nt active" onclick="showPage('dashboard',this)">Dashboard</button>
      <button class="nt" onclick="showPage('events',this)">Events</button>
      <button class="nt" onclick="showPage('volunteers',this)">Volunteers</button>
      <button class="nt" onclick="showPage('analytics',this)">Analytics</button>
    </div>
    <div class="nav-tabs" id="vol-tabs" style="display:none">
      <button class="nt active" onclick="showPage('feed',this)">My shifts</button>
      <button class="nt" onclick="showPage('my-assignments',this)">My assignments</button>
      <button class="nt" onclick="showPage('profile',this)">Profile</button>
    </div>
    <div class="nav-right">
      <div id="user-badge" class="avatar"></div>
      <button class="btn btn-g" style="font-size:12px;padding:6px 12px" onclick="logout()">Logout</button>
    </div>
  </nav>

  <!-- ── COORDINATOR PAGES ── -->
  <div id="page-dashboard" class="page active">
    <div class="stats" id="stat-cards"><div class="loading">Loading<span class="dot">.</span><span class="dot">.</span><span class="dot">.</span></div></div>
    <div class="g2">
      <div>
        <div class="card">
          <div class="card-title">Upcoming events <span class="card-action" onclick="showPageByName('events')">Manage →</span></div>
          <div id="dash-events"><div class="loading">Loading…</div></div>
        </div>
        <div class="gap"></div>
        <div class="card">
          <div class="card-title">Skills gap report <span class="card-action" onclick="showPageByName('volunteers')">View volunteers →</span></div>
          <div id="dash-gap"><div class="loading">Loading…</div></div>
        </div>
      </div>
      <div>
        <div class="card">
          <div class="card-title">Volunteer health <span class="card-action" onclick="showPageByName('volunteers')">View all →</span></div>
          <div id="dash-health"><div class="loading">Loading…</div></div>
        </div>
        <div class="gap"></div>
        <div class="card">
          <div class="card-title">Top volunteers</div>
          <div id="dash-top"><div class="loading">Loading…</div></div>
        </div>
      </div>
    </div>
  </div>

  <div id="page-events" class="page">
    <div class="g2" style="align-items:flex-start">
      <div>
        <div class="card">
          <div class="card-title">Create new event</div>
          <div class="form-row"><div class="form-label">Event name</div><input class="form-input" id="ev-title" placeholder="e.g. Flood relief — Coastal TN"></div>
          <div class="form-row"><div class="form-label">Event type</div>
            <select class="form-select" id="ev-type">
              <option value="">Select type…</option>
              <option value="flood">Flood / disaster relief</option>
              <option value="medical">Medical camp</option>
              <option value="food">Food drive</option>
              <option value="digital">Digital literacy</option>
              <option value="environment">Environmental / plantation</option>
            </select>
          </div>
          <div class="form-row"><div class="form-label">Location</div><input class="form-input" id="ev-loc" placeholder="City, State"></div>
          <div class="form-row"><div class="form-label">Description</div><input class="form-input" id="ev-desc" placeholder="Brief description"></div>
          <div class="form-grid2">
            <div class="form-row"><div class="form-label">Start date</div><input class="form-input" id="ev-start" type="datetime-local"></div>
            <div class="form-row"><div class="form-label">Expected crowd</div><input class="form-input" id="ev-crowd" type="number" placeholder="e.g. 1500"></div>
          </div>
          <div style="display:flex;gap:8px">
            <button class="btn btn-o" onclick="previewShifts()">Preview AI shifts</button>
            <button class="btn btn-p" onclick="createEvent()">Create event →</button>
          </div>
          <div id="shift-preview" style="margin-top:14px"></div>
        </div>
      </div>
      <div>
        <div class="card">
          <div class="card-title">All events</div>
          <div id="events-list"><div class="loading">Loading…</div></div>
        </div>
      </div>
    </div>
    <div class="gap"></div>
    <div class="card" id="event-detail-card" style="display:none">
      <div id="event-detail"></div>
    </div>
  </div>

  <div id="page-volunteers" class="page">
    <div class="card" style="margin-bottom:16px">
      <div style="display:flex;gap:10px;align-items:center">
        <input class="form-input" id="vol-search-loc" placeholder="Filter by city" style="max-width:200px">
        <button class="btn btn-p" onclick="loadVolunteers()">Search</button>
        <button class="btn btn-g" onclick="document.getElementById('vol-search-loc').value='';loadVolunteers()">Clear</button>
      </div>
    </div>
    <div class="card">
      <div class="card-title">Volunteer directory (<span id="vol-count">0</span>)</div>
      <div id="vol-list"><div class="loading">Loading…</div></div>
    </div>
  </div>

  <div id="page-analytics" class="page">
    <div class="stats" id="analytics-stats"><div class="loading">Loading…</div></div>
    <div class="g3">
      <div class="card">
        <div class="card-title">Skills gap</div>
        <div id="an-gap"><div class="loading">Loading…</div></div>
      </div>
      <div class="card">
        <div class="card-title">Top volunteers</div>
        <div id="an-top"><div class="loading">Loading…</div></div>
      </div>
      <div class="card">
        <div class="card-title">Event fill rates</div>
        <div id="an-fill"><div class="loading">Loading…</div></div>
      </div>
    </div>
  </div>

  <!-- ── VOLUNTEER PAGES ── -->
  <div id="page-feed" class="page">
    <div class="mobile-wrap">
      <div class="phone">
        <div class="phone-screen">
          <div class="ph-bar"><span>9:41</span><span>◼◼◼</span></div>
          <div class="ph-hdr">
            <div class="ph-hdr-t" id="feed-greeting">Good morning 👋</div>
            <div class="ph-hdr-s" id="feed-sub">Loading your matches…</div>
          </div>
          <div class="ph-body" id="feed-body"><div class="loading">Loading<span class="dot">.</span><span class="dot">.</span><span class="dot">.</span></div></div>
          <div class="ph-nav">
            <div class="ph-ni active">
              <span class="ph-icon">🏠</span>Feed
            </div>
          </div>
        </div>
      </div>
      <div class="right-panel">
        <div><div class="rp-title">How your feed works</div><div class="rp-body">Shifts are ranked by match score — a blend of your skill proficiency (40%), past reliability (30%), proximity (20%), and burnout headroom (10%). Best fits always float to the top.</div></div>
        <div><div class="rp-title">One-tap accept</div><div class="rp-body">Tap Accept to instantly confirm your spot. Declining a shift logs it as training data to improve future recommendations.</div></div>
        <div><div class="rp-title">Burnout protection</div><div class="rp-body">If you're near your monthly hour cap, shifts stop appearing automatically. Update your cap in Profile.</div></div>
      </div>
    </div>
  </div>

  <div id="page-my-assignments" class="page">
    <div class="card">
      <div class="card-title">My confirmed assignments</div>
      <div id="my-assignments-list"><div class="loading">Loading…</div></div>
    </div>
  </div>

  <div id="page-profile" class="page">
    <div class="g2" style="align-items:flex-start">
      <div>
        <div class="card">
          <div class="card-title">My profile</div>
          <div id="profile-view"><div class="loading">Loading…</div></div>
        </div>
      </div>
      <div>
        <div class="card">
          <div class="card-title">Edit profile</div>
          <div class="form-row"><div class="form-label">Name</div><input class="form-input" id="p-name"></div>
          <div class="form-row"><div class="form-label">City</div><input class="form-input" id="p-loc"></div>
          <div class="form-row"><div class="form-label">Bio</div><input class="form-input" id="p-bio" placeholder="A short bio"></div>
          <div class="form-row"><div class="form-label">Phone</div><input class="form-input" id="p-phone"></div>
          <div class="form-row"><div class="form-label">Monthly hour cap</div><input class="form-input" id="p-cap" type="number"></div>
          <button class="btn btn-p" onclick="saveProfile()">Save changes</button>
          <div class="gap"></div>
          <div class="card-title" style="margin-top:16px">Add a skill</div>
          <div class="form-row"><div class="form-label">Skill</div>
            <select class="form-select" id="p-skill-select"><option value="">Loading skills…</option></select>
          </div>
          <div class="form-row"><div class="form-label">Proficiency (1-10)</div><input class="form-input" id="p-prof" type="number" min="1" max="10" value="5"></div>
          <button class="btn btn-o" onclick="addSkill()">+ Add skill</button>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
// ══════════════════════════════════════════════════
// API
// ══════════════════════════════════════════════════
const API = '';
let TOKEN = localStorage.getItem('vos_token') || '';
let ME    = null;

async function api(method, path, body){
  const opts = {method, headers:{'Content-Type':'application/json'}};
  if(TOKEN) opts.headers['Authorization'] = 'Bearer '+TOKEN;
  if(body)  opts.body = JSON.stringify(body);
  const r = await fetch(API+'/api'+path, opts);
  const d = await r.json();
  if(!r.ok) throw new Error(d.error || 'Request failed');
  return d;
}

function toast(msg, duration=3000){
  const el = document.createElement('div');
  el.className = 'toast'; el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(()=>el.remove(), duration);
}

// ══════════════════════════════════════════════════
// AUTH
// ══════════════════════════════════════════════════
let authMode = 'login';

function toggleAuthMode(){
  authMode = authMode==='login'?'register':'login';
  const isReg = authMode==='register';
  document.getElementById('auth-name-row').style.display  = isReg?'block':'none';
  document.getElementById('auth-role-row').style.display  = isReg?'block':'none';
  document.getElementById('auth-loc-row').style.display   = isReg?'block':'none';
  document.getElementById('auth-btn').textContent         = isReg?'Create account':'Sign in';
  document.getElementById('auth-toggle-link').textContent = isReg?'Already have an account? Sign in':'Don\'t have an account? Sign up';
  document.getElementById('auth-err').style.display = 'none';
}

async function doAuth(){
  const email = document.getElementById('auth-email').value.trim();
  const pass  = document.getElementById('auth-password').value;
  const btn   = document.getElementById('auth-btn');
  const errEl = document.getElementById('auth-err');
  errEl.style.display = 'none';
  btn.disabled = true; btn.textContent = 'Please wait…';
  try{
    let data;
    if(authMode==='login'){
      data = await api('POST','/auth/login',{email,password:pass});
    } else {
      const name = document.getElementById('auth-name').value.trim();
      const role = document.getElementById('auth-role').value;
      const loc  = document.getElementById('auth-loc').value.trim();
      data = await api('POST','/auth/register',{name,email,password:pass,role,location:loc});
    }
    TOKEN = data.token;
    localStorage.setItem('vos_token', TOKEN);
    ME = data.user;
    initApp();
  } catch(e){
    errEl.textContent = e.message; errEl.style.display='block';
    btn.disabled=false; btn.textContent=authMode==='login'?'Sign in':'Create account';
  }
}

function logout(){
  TOKEN=''; ME=null; localStorage.removeItem('vos_token');
  document.getElementById('main-app').style.display='none';
  document.getElementById('auth-screen').style.display='flex';
}

// ══════════════════════════════════════════════════
// APP INIT
// ══════════════════════════════════════════════════
async function initApp(){
  if(!ME){
    try{ ME = await api('GET','/auth/me'); } catch(e){ logout(); return; }
  }
  document.getElementById('auth-screen').style.display='none';
  document.getElementById('main-app').style.display='block';
  const ub = document.getElementById('user-badge');
  ub.textContent = ME.name.split(' ').map(w=>w[0]).join('').slice(0,2).toUpperCase();
  ub.style.background = ME.avatar_color+'33';
  ub.style.color = ME.avatar_color;

  if(ME.role==='coordinator'){
    document.getElementById('coord-tabs').style.display='flex';
    document.getElementById('vol-tabs').style.display='none';
    loadDashboard();
  } else {
    document.getElementById('vol-tabs').style.display='flex';
    document.getElementById('coord-tabs').style.display='none';
    loadFeed();
    loadMyAssignments();
    loadProfile();
  }
}

function showPage(name, tabEl){
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.nt').forEach(t=>t.classList.remove('active'));
  document.getElementById('page-'+name).classList.add('active');
  if(tabEl) tabEl.classList.add('active');
  // lazy load
  if(name==='events')     { loadEvents(); }
  if(name==='volunteers') { loadVolunteers(); }
  if(name==='analytics')  { loadAnalytics(); }
}

function showPageByName(name){
  const tabs = document.querySelectorAll('.nt');
  const map  = {dashboard:0,events:1,volunteers:2,analytics:3,feed:0,'my-assignments':1,profile:2};
  showPage(name, tabs[map[name]||0]);
}

// ══════════════════════════════════════════════════
// COORDINATOR — DASHBOARD
// ══════════════════════════════════════════════════
async function loadDashboard(){
  try{
    const [ov, events, gap, top] = await Promise.all([
      api('GET','/analytics/overview'),
      api('GET','/events?status=open'),
      api('GET','/analytics/skills-gap'),
      api('GET','/analytics/top-volunteers'),
    ]);
    renderStats(ov);
    renderDashEvents(events);
    renderDashGap(gap);
    renderDashHealth(top);
    renderDashTop(top);
  }catch(e){ toast('Error loading dashboard: '+e.message); }
}

function renderStats(ov){
  document.getElementById('stat-cards').innerHTML = `
    <div class="stat"><div class="stat-label">Active volunteers</div><div class="stat-val" style="color:var(--teal)">${ov.total_volunteers}</div><div class="stat-sub">${ov.open_events} open events</div></div>
    <div class="stat"><div class="stat-label">Avg fill rate</div><div class="stat-val" style="color:var(--green)">${ov.avg_fill_rate}%</div><div class="stat-sub">Across all events</div></div>
    <div class="stat"><div class="stat-label">Total hours delivered</div><div class="stat-val" style="color:var(--teal)">${ov.total_hours}</div><div class="stat-sub">By all volunteers</div></div>
    <div class="stat"><div class="stat-label">Burnout risk flags</div><div class="stat-val" style="color:var(--coral)">${ov.burnout_flags}</div><div class="stat-sub">Near monthly cap</div></div>
  `;
}

function renderDashEvents(events){
  if(!events.length){ document.getElementById('dash-events').innerHTML='<div class="empty">No open events</div>'; return; }
  document.getElementById('dash-events').innerHTML = events.slice(0,5).map(e=>{
    const fr = e.fill_rate;
    const color = fr>=90?'var(--green)':fr>=60?'var(--amber)':'var(--coral)';
    return `<div class="vrow" style="cursor:pointer" onclick="openEventDetail('${e.id}')">
      <div style="width:8px;height:8px;border-radius:50%;background:${color};flex-shrink:0"></div>
      <div class="vinfo"><div class="vname">${e.title}</div><div class="vmeta">${fmtDate(e.starts_at)} · ${e.expected_crowd.toLocaleString()} expected</div></div>
      <div>
        <div class="bar-bg" style="width:80px"><div class="bar-fill" style="width:${fr}%;background:${color}"></div></div>
        <div style="font-size:11px;color:${color};font-weight:600;margin-top:2px">${fr}% filled</div>
      </div>
    </div>`;
  }).join('');
}

function renderDashGap(gap){
  if(!gap.length){ document.getElementById('dash-gap').innerHTML='<div class="empty">No gaps detected 🎉</div>'; return; }
  const max = gap[0].shortage;
  document.getElementById('dash-gap').innerHTML = gap.map(g=>`
    <div class="gap-row">
      <div class="gap-name">${g.skill}</div>
      <div class="gap-bar-bg"><div class="gap-bar-fill" style="width:${(g.shortage/max*100)}%;background:var(--coral)"></div></div>
      <div class="gap-count">−${g.shortage}</div>
    </div>`).join('');
}

function renderDashHealth(vols){
  document.getElementById('dash-health').innerHTML = vols.slice(0,5).map(v=>{
    const risk = v.hours_this_month / (v.monthly_cap||20);
    const color = risk>=0.8?'var(--coral)':risk>=0.6?'var(--amber)':'var(--green)';
    const label = risk>=0.8?'High risk':risk>=0.6?'Medium':'Healthy';
    return `<div class="vrow">
      <div class="vav" style="background:${v.avatar_color}22;color:${v.avatar_color}">${initials(v.name)}</div>
      <div class="vinfo"><div class="vname">${v.name}</div><div class="vmeta">${v.hours_this_month}/${v.monthly_cap} hrs this month</div></div>
      <div style="width:70px">
        <div class="bar-bg"><div class="bar-fill" style="width:${Math.min(risk*100,100)}%;background:${color}"></div></div>
        <div style="font-size:10px;color:${color};font-weight:500;margin-top:2px">${label}</div>
      </div>
    </div>`;
  }).join('');
}

function renderDashTop(vols){
  document.getElementById('dash-top').innerHTML = vols.slice(0,5).map((v,i)=>`
    <div class="vrow">
      <div style="font-size:13px;font-weight:700;color:${i===0?'var(--amber)':'var(--t3)'};width:18px">${i+1}</div>
      <div class="vav" style="background:${v.avatar_color}22;color:${v.avatar_color}">${initials(v.name)}</div>
      <div class="vinfo"><div class="vname">${v.name}</div><div class="vmeta">${v.total_hours} hrs · ${v.location}</div></div>
      <span class="badge bt">${v.reliability_score}★</span>
    </div>`).join('');
}

// ══════════════════════════════════════════════════
// COORDINATOR — EVENTS
// ══════════════════════════════════════════════════
async function loadEvents(){
  try{
    const events = await api('GET','/events');
    document.getElementById('events-list').innerHTML = events.length ? events.map(e=>`
      <div class="vrow" style="cursor:pointer" onclick="openEventDetail('${e.id}')">
        <div class="vinfo">
          <div class="vname">${e.title}</div>
          <div class="vmeta">${e.location} · ${fmtDate(e.starts_at)} · <span class="badge ${statusBadge(e.status)}">${e.status}</span></div>
        </div>
        <div style="text-align:right">
          <div style="font-size:13px;font-weight:600;color:${e.fill_rate>=80?'var(--green)':e.fill_rate>=50?'var(--amber)':'var(--coral)'}">${e.fill_rate}%</div>
          <div style="font-size:11px;color:var(--t3)">filled</div>
        </div>
      </div>`).join('') : '<div class="empty">No events yet. Create one!</div>';
  }catch(e){ toast('Error: '+e.message); }
}

async function previewShifts(){
  const type  = document.getElementById('ev-type').value;
  const crowd = parseInt(document.getElementById('ev-crowd').value)||0;
  if(!type||!crowd){ toast('Select event type and crowd size first'); return; }
  try{
    const r = await api('POST','/events/predict-shifts',{event_type:type,crowd});
    const total = r.plan.reduce((s,p)=>s+p.count,0);
    document.getElementById('shift-preview').innerHTML = `
      <div style="font-size:12px;color:var(--t3);margin-bottom:10px">AI prediction for ${crowd} attendees · ${total} volunteers needed</div>
      <table><thead><tr><th>Role</th><th>Skill</th><th>Count</th></tr></thead><tbody>
      ${r.plan.map(p=>`<tr><td style="font-weight:500">${p.role}</td><td><span class="badge bt">${p.skill||'No requirement'}</span></td><td style="font-weight:700">${p.count}</td></tr>`).join('')}
      </tbody></table>`;
  }catch(e){ toast('Error: '+e.message); }
}

async function createEvent(){
  const title = document.getElementById('ev-title').value.trim();
  const type  = document.getElementById('ev-type').value;
  const loc   = document.getElementById('ev-loc').value.trim();
  const desc  = document.getElementById('ev-desc').value.trim();
  const start = document.getElementById('ev-start').value;
  const crowd = parseInt(document.getElementById('ev-crowd').value)||0;
  if(!title) { toast('Event name is required'); return; }
  try{
    const e = await api('POST','/events',{title,event_type:type,location:loc,description:desc,starts_at:start?new Date(start).toISOString():null,expected_crowd:crowd});
    toast('✅ Event created with AI-generated shifts!');
    loadEvents();
    openEventDetail(e.id);
    document.getElementById('ev-title').value='';
    document.getElementById('shift-preview').innerHTML='';
  }catch(e){ toast('Error: '+e.message); }
}

async function openEventDetail(eid){
  const card = document.getElementById('event-detail-card');
  card.style.display='block';
  card.scrollIntoView({behavior:'smooth',block:'start'});
  document.getElementById('event-detail').innerHTML='<div class="loading">Loading event…</div>';
  try{
    const e = await api('GET','/events/'+eid);
    document.getElementById('event-detail').innerHTML = `
      <div class="card-title">${e.title} <span class="badge ${statusBadge(e.status)}">${e.status}</span>
        <div style="display:flex;gap:8px">
          <button class="btn btn-p" style="font-size:12px;padding:6px 12px" onclick="autoAssign('${e.id}')">⚡ Auto-assign all</button>
          <button class="btn btn-d" style="font-size:12px;padding:6px 12px" onclick="deleteEvent('${e.id}')">Delete</button>
        </div>
      </div>
      <div style="font-size:13px;color:var(--t2);margin-bottom:16px">${e.location} · ${fmtDate(e.starts_at)} · ${e.expected_crowd} expected · <strong>${e.fill_rate}% filled</strong></div>
      <table><thead><tr><th>Role</th><th>Skill required</th><th>Needed</th><th>Assigned</th><th>Status</th><th>Action</th></tr></thead><tbody>
      ${e.shifts.map(s=>`
        <tr>
          <td style="font-weight:500">${s.role_name}</td>
          <td><span class="badge bt">${s.skill_name}</span></td>
          <td>${s.volunteers_needed}</td>
          <td>${s.assigned_count}</td>
          <td><span class="badge ${s.open_spots===0?'bg2':'bc'}">${s.open_spots===0?'Full':s.open_spots+' open'}</span></td>
          <td>
            ${s.open_spots>0?`<button class="btn btn-o" style="font-size:12px;padding:4px 10px" onclick="loadCandidates('${s.id}','${s.role_name}')">Find volunteers</button>`:'<span style="font-size:12px;color:var(--green)">✓ Complete</span>'}
          </td>
        </tr>`).join('')}
      </tbody></table>
      <div id="candidates-panel-${e.id}" style="margin-top:16px"></div>
    `;
  }catch(ex){ toast('Error: '+ex.message); }
}

async function loadCandidates(shiftId, roleName){
  const panel = document.querySelector('[id^="candidates-panel-"]');
  if(!panel) return;
  panel.innerHTML = `<div class="card-title">Top candidates for "${roleName}"</div><div class="loading">Ranking volunteers…</div>`;
  try{
    const candidates = await api('GET','/shifts/'+shiftId+'/candidates');
    if(!candidates.length){ panel.innerHTML += '<div class="empty">No matching volunteers found</div>'; return; }
    panel.innerHTML = `
      <div class="card-title">Top candidates — ${roleName}</div>
      ${candidates.slice(0,5).map((v,i)=>`
        <div class="vrow">
          <div style="font-size:12px;font-weight:700;color:${i===0?'var(--teal)':'var(--t3)'};width:20px">${i+1}</div>
          <div class="vav" style="background:${v.avatar_color}22;color:${v.avatar_color}">${initials(v.name)}</div>
          <div class="vinfo">
            <div class="vname">${v.name}</div>
            <div class="vmeta">${v.location} · ${v.reliability_score}★ · ${v.hours_this_month}/${v.monthly_cap}h this month</div>
          </div>
          <div style="min-width:80px;text-align:center">
            <div class="bar-bg"><div class="bar-fill" style="width:${v.match_score}%;background:var(--teal)"></div></div>
            <div style="font-size:11px;color:var(--teal);font-weight:700;margin-top:2px">${v.match_score}% match</div>
          </div>
          <button class="btn btn-p" style="font-size:12px;padding:5px 10px" onclick="assignVolunteer('${shiftId}','${v.id}',this)">Assign</button>
        </div>`).join('')}
    `;
  }catch(ex){ toast('Error: '+ex.message); }
}

async function assignVolunteer(shiftId, volId, btn){
  try{
    await api('POST','/shifts/'+shiftId+'/assign',{volunteer_id:volId});
    btn.textContent='Assigned ✓'; btn.disabled=true; btn.className='btn btn-g';
    toast('✅ Volunteer assigned!');
  }catch(e){ toast('Error: '+e.message); }
}

async function autoAssign(eid){
  try{
    const r = await api('POST','/events/'+eid+'/auto-assign');
    toast('⚡ Auto-assigned! Open event to see results.');
    openEventDetail(eid);
    loadDashboard();
  }catch(e){ toast('Error: '+e.message); }
}

async function deleteEvent(eid){
  if(!confirm('Delete this event and all its shifts?')) return;
  try{
    await api('DELETE','/events/'+eid);
    toast('Event deleted'); 
    document.getElementById('event-detail-card').style.display='none';
    loadEvents(); loadDashboard();
  }catch(e){ toast('Error: '+e.message); }
}

// ══════════════════════════════════════════════════
// COORDINATOR — VOLUNTEERS
// ══════════════════════════════════════════════════
async function loadVolunteers(){
  try{
    const loc  = document.getElementById('vol-search-loc')?.value||'';
    const vols = await api('GET','/volunteers'+(loc?'?location='+encodeURIComponent(loc):''));
    document.getElementById('vol-count').textContent = vols.length;
    document.getElementById('vol-list').innerHTML = vols.length ? `
      <table><thead><tr><th>Name</th><th>Location</th><th>Skills</th><th>Hours</th><th>Reliability</th><th>Burnout</th></tr></thead><tbody>
      ${vols.map(v=>{
        const risk = v.hours_this_month/(v.monthly_cap||20);
        const color = risk>=0.8?'var(--coral)':risk>=0.6?'var(--amber)':'var(--green)';
        return `<tr>
          <td><div style="display:flex;align-items:center;gap:8px">
            <div class="vav" style="background:${v.avatar_color}22;color:${v.avatar_color};width:28px;height:28px;font-size:10px">${initials(v.name)}</div>
            <div><div class="vname">${v.name}</div><div class="vmeta">${v.email}</div></div>
          </div></td>
          <td>${v.location||'—'}</td>
          <td>${v.skills.map(s=>`<span class="badge bt" style="margin:1px;font-size:10px">${s.skill_name} ${s.proficiency}/10</span>`).join('')||'<span class="badge bx">No skills</span>'}</td>
          <td style="font-weight:600">${v.total_hours}h</td>
          <td><span class="badge bt">${v.reliability_score}★</span></td>
          <td><div style="width:60px"><div class="bar-bg"><div class="bar-fill" style="width:${Math.min(risk*100,100)}%;background:${color}"></div></div><div style="font-size:10px;color:${color};margin-top:1px">${v.hours_this_month}/${v.monthly_cap}h</div></div></td>
        </tr>`;}).join('')}
      </tbody></table>` : '<div class="empty">No volunteers found</div>';
  }catch(e){ toast('Error: '+e.message); }
}

// ══════════════════════════════════════════════════
// COORDINATOR — ANALYTICS
// ══════════════════════════════════════════════════
async function loadAnalytics(){
  try{
    const [ov, gap, top, events] = await Promise.all([
      api('GET','/analytics/overview'),
      api('GET','/analytics/skills-gap'),
      api('GET','/analytics/top-volunteers'),
      api('GET','/events'),
    ]);
    renderStats(ov);
    document.getElementById('analytics-stats').innerHTML = document.getElementById('stat-cards').innerHTML;

    // Gap
    const maxG = gap.length ? gap[0].shortage : 1;
    document.getElementById('an-gap').innerHTML = gap.length ? gap.map(g=>`
      <div class="gap-row">
        <div class="gap-name">${g.skill}</div>
        <div class="gap-bar-bg"><div class="gap-bar-fill" style="width:${g.shortage/maxG*100}%;background:var(--coral)"></div></div>
        <div class="gap-count">−${g.shortage}</div>
      </div>`).join('') : '<div class="empty">No gaps 🎉</div>';

    // Top
    document.getElementById('an-top').innerHTML = top.slice(0,8).map((v,i)=>`
      <div class="vrow">
        <div style="font-size:12px;font-weight:700;color:${i<3?'var(--amber)':'var(--t3)'};width:20px">${i+1}</div>
        <div class="vav" style="background:${v.avatar_color}22;color:${v.avatar_color}">${initials(v.name)}</div>
        <div class="vinfo"><div class="vname">${v.name}</div><div class="vmeta">${v.location}</div></div>
        <div style="font-size:13px;font-weight:600;color:var(--teal)">${v.total_hours}h</div>
      </div>`).join('');

    // Fill rate
    document.getElementById('an-fill').innerHTML = events.filter(e=>e.shifts.length).slice(0,6).map(e=>`
      <div style="margin-bottom:10px">
        <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:4px">
          <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:160px">${e.title}</span>
          <span style="font-weight:700;color:${e.fill_rate>=80?'var(--green)':e.fill_rate>=50?'var(--amber)':'var(--coral)'}">${e.fill_rate}%</span>
        </div>
        <div class="bar-bg"><div class="bar-fill" style="width:${e.fill_rate}%;background:${e.fill_rate>=80?'var(--green)':e.fill_rate>=50?'var(--amber)':'var(--coral)'}"></div></div>
      </div>`).join('') || '<div class="empty">No events yet</div>';
  }catch(e){ toast('Error loading analytics: '+e.message); }
}

// ══════════════════════════════════════════════════
// VOLUNTEER — FEED
// ══════════════════════════════════════════════════
async function loadFeed(){
  const hour = new Date().getHours();
  const greet = hour<12?'Good morning':'hour<17?Good afternoon':'Good evening';
  document.getElementById('feed-greeting').textContent = (hour<12?'Good morning':'hour<17?Good afternoon':'Good evening')+`, ${ME.name.split(' ')[0]} 👋`;
  try{
    const feed = await api('GET','/my/feed');
    document.getElementById('feed-sub').textContent = feed.length ? `${feed.length} shift matches for you` : 'No new matches right now';
    if(!feed.length){
      document.getElementById('feed-body').innerHTML = `
        <div class="impact" style="background:var(--teal)">
          <div class="impact-num">${ME.total_hours}h</div>
          <div class="impact-lbl">Total hours volunteered</div>
          <div class="impact-sub">Check back soon for new shifts!</div>
        </div>`;
      return;
    }
    document.getElementById('feed-body').innerHTML = `
      <div class="impact">
        <div class="impact-num">${ME.total_hours}h</div>
        <div class="impact-lbl">Total hours volunteered</div>
        <div class="impact-sub">You're making a real difference!</div>
      </div>
      ${feed.slice(0,6).map(item=>`
        <div class="sc" id="sc-${item.shift.id}">
          <div style="display:flex;align-items:flex-start;justify-content:space-between">
            <div><div class="sc-org">${item.event.location}</div><div class="sc-title">${item.shift.role_name}</div></div>
            <span class="ms-badge">${item.match_score}% match</span>
          </div>
          <div class="sc-tags">
            <span class="sc-tag">📅 ${fmtDate(item.event.starts_at)}</span>
            <span class="sc-tag">📍 ${item.event.location}</span>
            <span class="sc-tag">🎯 ${item.shift.skill_name}</span>
            <span class="sc-tag">${item.shift.open_spots} spots left</span>
          </div>
          <div class="sc-foot">
            <span style="font-size:12px;color:var(--t3)">${item.event.title}</span>
            <div class="sc-btns">
              <button class="btn btn-g" style="padding:5px 11px;font-size:12px" onclick="respondShift('${item.shift.id}','decline',this)">Decline</button>
              <button class="btn btn-p" style="padding:5px 11px;font-size:12px" onclick="respondShift('${item.shift.id}','accept',this)">Accept ✓</button>
            </div>
          </div>
        </div>`).join('')}
    `;
  }catch(e){ toast('Error: '+e.message); }
}

async function respondShift(shiftId, action, btn){
  try{
    await api('POST','/my/respond',{shift_id:shiftId,action});
    const card = document.getElementById('sc-'+shiftId);
    if(action==='accept'){
      card.style.borderColor='var(--teal)'; card.style.background='var(--tl)';
      card.querySelector('.sc-btns').innerHTML='<span style="font-size:12px;font-weight:600;color:var(--teal)">✓ Confirmed!</span>';
      toast('✅ Shift accepted!');
      loadMyAssignments();
    } else {
      card.style.opacity='0.4';
      toast('Shift declined');
    }
  }catch(e){ toast('Error: '+e.message); }
}

// ══════════════════════════════════════════════════
// VOLUNTEER — ASSIGNMENTS
// ══════════════════════════════════════════════════
async function loadMyAssignments(){
  try{
    const items = await api('GET','/my/assignments');
    const confirmed = items.filter(a=>a.status==='confirmed');
    document.getElementById('my-assignments-list').innerHTML = confirmed.length ? `
      <table><thead><tr><th>Event</th><th>Role</th><th>Location</th><th>Date</th><th>Match score</th><th>Status</th></tr></thead><tbody>
      ${confirmed.map(a=>`<tr>
        <td style="font-weight:500">${a.event.title||'—'}</td>
        <td>${a.shift.role_name||'—'}</td>
        <td>${a.event.location||'—'}</td>
        <td>${fmtDate(a.event.starts_at)}</td>
        <td><span class="badge bt">${a.match_score}%</span></td>
        <td><span class="badge bg2">Confirmed ✓</span></td>
      </tr>`).join('')}
      </tbody></table>` : '<div class="empty">No confirmed assignments yet. Accept some shifts from your feed!</div>';
  }catch(e){ toast('Error: '+e.message); }
}

// ══════════════════════════════════════════════════
// VOLUNTEER — PROFILE
// ══════════════════════════════════════════════════
async function loadProfile(){
  try{
    const v = await api('GET','/auth/me');
    ME = v;
    document.getElementById('p-name').value = v.name||'';
    document.getElementById('p-loc').value  = v.location||'';
    document.getElementById('p-bio').value  = v.bio||'';
    document.getElementById('p-phone').value= v.phone||'';
    document.getElementById('p-cap').value  = v.monthly_cap||20;
    const risk = v.hours_this_month/(v.monthly_cap||20);
    const color = risk>=0.8?'var(--coral)':risk>=0.6?'var(--amber)':'var(--green)';
    document.getElementById('profile-view').innerHTML = `
      <div style="display:flex;align-items:center;gap:14px;margin-bottom:16px">
        <div class="vav" style="width:52px;height:52px;font-size:18px;background:${v.avatar_color}22;color:${v.avatar_color}">${initials(v.name)}</div>
        <div><div style="font-size:16px;font-weight:700">${v.name}</div>
          <div style="font-size:13px;color:var(--t2)">${v.location} · ${v.reliability_score}★</div>
          <div style="margin-top:6px"><span class="badge bt">${v.total_hours}h total</span></div>
        </div>
      </div>
      <div style="margin-bottom:14px">
        <div style="font-size:12px;font-weight:500;color:var(--t2);margin-bottom:8px">My skills</div>
        ${v.skills.length ? v.skills.map(s=>`<span class="skill-pill">${s.skill_name} <span style="font-size:10px;color:var(--t3)">· ${s.proficiency}/10${s.verified?' · ✓':''}</span> <span style="cursor:pointer;color:var(--coral);margin-left:6px" onclick="removeSkill('${s.id}')">×</span></span>`).join('') : '<div style="font-size:13px;color:var(--t3)">No skills added yet</div>'}
      </div>
      <div>
        <div style="font-size:12px;font-weight:500;color:var(--t2);margin-bottom:6px">Monthly hours — ${v.hours_this_month}/${v.monthly_cap}</div>
        <div class="bar-bg"><div class="bar-fill" style="width:${Math.min(risk*100,100)}%;background:${color}"></div></div>
      </div>`;

    // Load skills for dropdown
    const skills = await api('GET','/skills');
    document.getElementById('p-skill-select').innerHTML = '<option value="">Select a skill…</option>' +
      skills.map(s=>`<option value="${s.name}">${s.name} (${s.category})</option>`).join('');
  }catch(e){ toast('Error: '+e.message); }
}

async function saveProfile(){
  try{
    await api('PUT','/volunteers/'+ME.id,{
      name: document.getElementById('p-name').value,
      location: document.getElementById('p-loc').value,
      bio: document.getElementById('p-bio').value,
      phone: document.getElementById('p-phone').value,
      monthly_cap: parseFloat(document.getElementById('p-cap').value)||20,
    });
    toast('✅ Profile saved!'); loadProfile();
  }catch(e){ toast('Error: '+e.message); }
}

async function addSkill(){
  const name = document.getElementById('p-skill-select').value;
  const prof = parseInt(document.getElementById('p-prof').value)||5;
  if(!name){ toast('Select a skill first'); return; }
  try{
    await api('POST','/volunteers/'+ME.id+'/skills',{skill_name:name,proficiency:prof});
    toast('✅ Skill added!'); loadProfile();
  }catch(e){ toast('Error: '+e.message); }
}

async function removeSkill(vsId){
  try{
    await api('DELETE','/volunteers/'+ME.id+'/skills/'+vsId);
    toast('Skill removed'); loadProfile(); loadFeed();
  }catch(e){ toast('Error: '+e.message); }
}

// ══════════════════════════════════════════════════
// UTILS
// ══════════════════════════════════════════════════
function initials(name){ return (name||'?').split(' ').map(w=>w[0]).join('').slice(0,2).toUpperCase(); }
function fmtDate(iso){ if(!iso) return '—'; const d=new Date(iso); return d.toLocaleDateString('en-IN',{day:'numeric',month:'short',year:'numeric'}); }
function statusBadge(s){ return {open:'bt',draft:'bx',completed:'bg2',cancelled:'bc'}[s]||'bx'; }

// Boot
(async()=>{
  if(TOKEN){
    try{ ME = await api('GET','/auth/me'); initApp(); }
    catch(e){ TOKEN=''; localStorage.removeItem('vos_token'); }
  }
})();

// Enter key on auth
document.addEventListener('keydown', e=>{ if(e.key==='Enter' && document.getElementById('auth-screen').style.display!=='none') doAuth(); });
</script>
</body>
</html>"""

@app.route('/')
@app.route('/<path:p>')
def frontend(p=''):
    return Response(FRONTEND, mimetype='text/html')

# ══════════════════════════════════════════════════════════════════════════════
# STARTUP
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        seed()
    print("\n🚀 VolunteerOS running at → http://localhost:5000\n")
    app.run(debug=False, port=5000, host='0.0.0.0')
