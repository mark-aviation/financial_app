# 🔒 Setup Guide - Database Configuration

This project contains placeholder values for sensitive database credentials. To run locally:

## Step 1: Configure Database Connection

1. Copy `db_config.example.json` to `db_config.json`:
   ```bash
   cp db_config.example.json db_config.json
   ```

2. Edit `db_config.json` with your actual database credentials:
   ```json
   {
     "host": "your_actual_host",
     "user": "your_actual_user",
     "database": "expensis",
     "password": "your_actual_password"
   }
   ```

## Step 2: Never Commit Credentials

The following files are **automatically ignored** by Git and should never be committed:
- `db_config.json` (with real credentials)
- `.env` files
- All Python cache and virtual environment files

## Security Checklist Before Pushing to GitHub

✅ `db_config.json` contains placeholder values  
✅ `config.py` contains placeholder values  
✅ `.gitignore` excludes sensitive files  
✅ `.venv/` and `build/` folders are ignored  

## For CI/CD Deployments

If using GitHub Actions or similar, store credentials as **Secrets**:
- Go to repository Settings → Secrets → New repository secret
- Add secrets like `DB_HOST`, `DB_USER`, `DB_PASSWORD`
- Reference them in your deployment scripts with `${{ secrets.DB_HOST }}`

## Questions?

If you accidentally committed sensitive data:
1. Remove it from Git history: `git filter-branch`
2. Rotate your credentials immediately
3. Add `.gitignore` rules before re-pushing
