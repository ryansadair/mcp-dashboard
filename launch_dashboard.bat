@echo off
title Martin Capital — Portfolio Dashboard
cd /d "C:\Users\RyanAdair\Martin Capital Partners LLC\Eugene - Documents\Operations\Scripts\Portfolio Dashboard"
call venv\Scripts\activate.bat
start http://localhost:8501
streamlit run app.py
pause