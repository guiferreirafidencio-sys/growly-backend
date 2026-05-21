# admin.py — Blueprint admin + Model Analise
#
# ── INTEGRAÇÃO NO main.py ────────────────────────────────────
#
#   from admin import admin_bp, init_admin
#   init_admin(db, User)
#   app.register_blueprint(admin_bp)
#
#   (o db.create_all() do main já cria a tabela Analise)
#
# ── NO analisar.py, após análise bem-sucedida ────────────────
#
#   from admin import _Analise as Analise
#   from main import db
#   db.session.add(Analise(user_id=session["user_id"], rede=rede, url=url))
#   db.session.commit()
#
# ── NO .env ──────────────────────────────────────────────────
#
#   ADMIN_EMAIL=seu@gmail.com
#
# ─────────────────────────────────────────────────────────────

from flask import Blueprint, render_template, session, redirect, jsonify
from datetime import datetime, timedelta
from functools import wraps
import os

admin_bp = Blueprint("admin", __name__)

# ════════════════════════════════════════════════
# ESTADO GLOBAL — preenchido pelo init_admin()
# ════════════════════════════════════════════════

_db      = None
_User    = None
_Analise = None


def init_admin(db, User):
    """Chame no main.py: init_admin(db, User)"""
    global _db, _User, _Analise
    _db   = db
    _User = User

    class Analise(db.Model):
        __tablename__ = "analises"
        id        = db.Column(db.Integer, primary_key=True)
        user_id   = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        rede      = db.Column(db.String(50))
        url       = db.Column(db.String(500))
        criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    _Analise = Analise

# ════════════════════════════════════════════════
# DECORATOR — só admin entra
# ════════════════════════════════════════════════

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        admin_email = os.getenv("ADMIN_EMAIL", "").strip().lower()
        user_email  = session.get("email", "").strip().lower()
        if not user_email or user_email != admin_email:
            return redirect("/")
        return f(*args, **kwargs)
    return decorated


# ════════════════════════════════════════════════
# ROTAS
# ════════════════════════════════════════════════

@admin_bp.route("/admin")
@admin_required
def admin_page():
    return render_template('admin.html')


@admin_bp.route("/api/admin/stats")
@admin_required
def admin_stats():
    total_usuarios = _User.query.count()
    total_analises = _Analise.query.count()

    # ativos nos últimos 7 dias
    sete_dias   = datetime.utcnow() - timedelta(days=7)
    ativos_ids  = _db.session.query(_Analise.user_id).filter(
        _Analise.criado_em >= sete_dias
    ).distinct().all()
    usuarios_ativos = len(ativos_ids)

    # gráfico — últimos 30 dias
    trinta_dias  = datetime.utcnow() - timedelta(days=30)
    analises_mes = _Analise.query.filter(_Analise.criado_em >= trinta_dias).all()
    por_dia = {}
    for a in analises_mes:
        dia = a.criado_em.strftime("%Y-%m-%d")
        por_dia[dia] = por_dia.get(dia, 0) + 1

    grafico = []
    for i in range(29, -1, -1):
        dia = (datetime.utcnow() - timedelta(days=i)).strftime("%Y-%m-%d")
        grafico.append({"dia": dia, "total": por_dia.get(dia, 0)})

    # lista de usuários
    usuarios = []
    for u in _User.query.order_by(_User.id.desc()).all():
        count  = _Analise.query.filter_by(user_id=u.id).count()
        ultima = _Analise.query.filter_by(user_id=u.id).order_by(
            _Analise.criado_em.desc()
        ).first()
        usuarios.append({
            "id":        u.id,
            "google_id": u.google_id,
            "nome":      u.nome,
            "email":     u.email,
            "foto":      u.foto or "",
            "analises":  count,
            "ultima":    ultima.criado_em.strftime("%d/%m/%Y %H:%M") if ultima else "—"
        })

    return jsonify({
        "total_usuarios":  total_usuarios,
        "total_analises":  total_analises,
        "usuarios_ativos": usuarios_ativos,
        "grafico":         grafico,
        "usuarios":        usuarios
    })