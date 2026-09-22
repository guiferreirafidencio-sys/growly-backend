from datetime import datetime

from .database import db


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    google_id = db.Column(db.String(200), unique=True, nullable=False)
    nome = db.Column(db.String(200))
    email = db.Column(db.String(200), unique=True)
    foto = db.Column(db.String(500))


class Analise(db.Model):
    __tablename__ = "analises"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    rede = db.Column(db.String(50))
    url = db.Column(db.String(500))
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)
