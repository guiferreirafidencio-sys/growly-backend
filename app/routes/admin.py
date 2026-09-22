"""Administration dashboard routes."""

import os
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, jsonify, redirect, render_template, session

from app.database.database import db
from app.database.models import Analise, User

admin_bp = Blueprint("admin", __name__)


def admin_required(view):
    @wraps(view)
    def decorated(*args, **kwargs):
        admin_email = os.getenv("ADMIN_EMAIL", "").strip().lower()
        if not admin_email or session.get("email", "").strip().lower() != admin_email:
            return redirect("/")
        return view(*args, **kwargs)
    return decorated


@admin_bp.route("/admin")
@admin_required
def admin_page():
    return render_template("admin.html")


@admin_bp.route("/api/admin/stats")
@admin_required
def admin_stats():
    now = datetime.utcnow()
    recent = Analise.query.filter(Analise.criado_em >= now - timedelta(days=30)).all()
    by_day = {}
    for analysis in recent:
        day = analysis.criado_em.strftime("%Y-%m-%d")
        by_day[day] = by_day.get(day, 0) + 1

    users = []
    for user in User.query.order_by(User.id.desc()).all():
        latest = Analise.query.filter_by(user_id=user.id).order_by(Analise.criado_em.desc()).first()
        users.append({"id": user.id, "google_id": user.google_id, "nome": user.nome,
                      "email": user.email, "foto": user.foto or "",
                      "analises": Analise.query.filter_by(user_id=user.id).count(),
                      "ultima": latest.criado_em.strftime("%d/%m/%Y %H:%M") if latest else "—"})

    active = db.session.query(Analise.user_id).filter(
        Analise.criado_em >= now - timedelta(days=7)
    ).distinct().count()
    return jsonify({
        "total_usuarios": User.query.count(),
        "total_analises": Analise.query.count(),
        "usuarios_ativos": active,
        "grafico": [
            {"dia": (now - timedelta(days=offset)).strftime("%Y-%m-%d"),
             "total": by_day.get((now - timedelta(days=offset)).strftime("%Y-%m-%d"), 0)}
            for offset in range(29, -1, -1)
        ],
        "usuarios": users,
    })
