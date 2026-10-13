# Authentication Setup Inquiry Prompt

> **Superseded historical prompt.** Do not run it. CleanHouse now follows the transient lowercase `auth` alignment contract documented in [AUTHENTICATION_SYSTEM.md](AUTHENTICATION_SYSTEM.md).

Copy and paste this prompt into your other coding LLM application:

---

**Context:**
I'm working on a Python desktop application called CleanHouse that uses a hybrid web/desktop architecture. The frontend is HTML/CSS/JavaScript served via Flask, and the desktop app uses pywebview to wrap the web interface. I need to set up authentication (login/signup) with OAuth providers (Google, Microsoft, Apple, GitHub) and email/password authentication.

**Current State:**
- Frontend: HTML/CSS/JS files in `frontend/` directory
- Backend: Flask API in `backend/api/auth.py` with endpoints for `/api/auth/login`, `/api/auth/createAccount`, `/api/auth/oauth/<provider>`
- User Management: Sharded file-based user registry (similar to VVAULT structure)
- OAuth Flow: Partially implemented - can redirect to OAuth providers and handle callbacks
- Database: Using `UserService` and `DatabaseManager` from `models/user_model.py`

**What I Need:**
Please explain how you would set up the authentication system for this application. Specifically:

1. **Session Management:**
   - How should user sessions be managed after successful login/signup?
   - Should I use Flask sessions, JWT tokens, or another approach?
   - How do I maintain authentication state between the Flask backend and the frontend JavaScript?

2. **OAuth Flow Completion:**
   - After OAuth callback, how should I handle the authenticated user?
   - Should I create a session immediately, or redirect to a success page?
   - How do I pass user data from the backend to the frontend after OAuth?

3. **Login/Signup Form Submission:**
   - How should the frontend JavaScript submit login/signup forms to the Flask API?
   - What should happen after successful authentication?
   - How do I handle errors and display them to the user?

4. **Protected Routes/Pages:**
   - How should I protect pages/routes that require authentication?
   - How do I check if a user is logged in from the frontend?
   - How do I redirect unauthenticated users to the login page?

5. **State Management:**
   - How should I store the current user's information in the frontend?
   - Should I use localStorage, sessionStorage, or make API calls to check auth status?
   - How do I handle token/session expiration?

6. **Best Practices:**
   - What security considerations should I implement?
   - How should I handle password hashing and storage?
   - What about CSRF protection for forms?

**Technical Details:**
- Backend: Flask (Python 3.13)
- Frontend: Vanilla JavaScript (no frameworks)
- Desktop Wrapper: pywebview
- User Storage: File-based sharded registry (JSON files)
- OAuth Providers: Google, Microsoft, Apple, GitHub (using PKCE)

Please provide a comprehensive guide on how to implement this authentication system, including:
- Code examples for Flask routes
- JavaScript code for frontend authentication handling
- Session/token management approach
- Error handling patterns
- Security best practices

Thank you!

---

