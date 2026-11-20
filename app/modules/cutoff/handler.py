from fastapi import APIRouter, Request, Body
from app.engine import evaluate
from app.web import render
router=APIRouter()
@router.get('/cutoff')
def page(request:Request):
    return render(request,'cutoff')
@router.post('/api/cutoff')
def calculate(payload:dict=Body(default={})):
    return evaluate(payload,until=2)
