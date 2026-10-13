# CleanHouse Authentication Quick Reference

> **Superseded historical reference.** Do not implement this document. The canonical server-session architecture is [AUTHENTICATION_SYSTEM.md](AUTHENTICATION_SYSTEM.md).

**Quick setup guide for implementing authentication**

---

## Files Created/Modified

### Backend Files
- ✅ `backend/utils/jwt_utils.py` - JWT token generation and verification
- ✅ `backend/utils/csrf.py` - CSRF protection utilities
- ✅ `backend/api/auth.py` - **UPDATE REQUIRED** - Add JWT token generation to login/signup endpoints

### Frontend Files
- ✅ `frontend/js/auth-state.js` - Authentication state management
- ✅ `frontend/js/protected-routes.js` - Protected route handling
- ✅ `frontend/js/auth.js` - **UPDATE REQUIRED** - Update login/signup handlers to use JWT tokens
- ✅ `frontend/js/api-client.js` - **UPDATE REQUIRED** - Add auth headers to API requests

---

## Quick Implementation Steps

### 1. Install Required Python Packages

```bash
pip install PyJWT flask-session
```

### 2. Update Flask App Initialization

Add to your Flask app initialization (`backend/__init__.py` or `backend/app.py`):

```python
from flask_session import Session
import secrets
from pathlib import Path
import os

def create_app():
    app = Flask(__name__)
    
    # Generate secret key for sessions
    secret_key = os.getenv('FLASK_SECRET_KEY')
    if not secret_key:
        secret_key_file = Path.home() / '.cleanhouse' / '.flask_secret_key'
        if secret_key_file.exists():
            secret_key = secret_key_file.read_text().strip()
        else:
            secret_key = secrets.token_hex(32)
            secret_key_file.parent.mkdir(parents=True, exist_ok=True)
            secret_key_file.write_text(secret_key)
    
    app.config['SECRET_KEY'] = secret_key
    app.config['SESSION_TYPE'] = 'filesystem'
    app.config['SESSION_FILE_DIR'] = str(Path.home() / '.cleanhouse' / 'sessions')
    app.config['SESSION_PERMANENT'] = False
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SECURE'] = False  # Set to True in production with HTTPS
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    
    Session(app)
    
    return app
```

### 3. Update Auth Endpoints

In `backend/api/auth.py`, update login and signup endpoints to:

1. Import JWT utilities:
```python
from backend.utils.jwt_utils import generate_jwt_token, get_user_from_token
```

2. Generate JWT token after successful authentication:
```python
# After user authentication succeeds
jwt_token = generate_jwt_token({
    'user_id': user.user_id or str(user.id),
    'email': user.email,
    'full_name': user.full_name,
    'role': getattr(user, 'role', 'user')
})

return jsonify({
    'success': True,
    'token': jwt_token,  # Add this
    'user': user_data
})
```

3. Add `/auth/me` endpoint (see full guide)

4. Add `/auth/logout` endpoint (see full guide)

### 4. Update Frontend HTML Files

Add these scripts to `login.html` and `signup.html` (before closing `</body>`):

```html
<!-- Auth state management -->
<script src="js/auth-state.js"></script>
<!-- Protected routes -->
<script src="js/protected-routes.js"></script>
<!-- Auth handlers -->
<script src="js/auth.js"></script>
```

### 5. Update Frontend Auth Handlers

In `frontend/js/auth.js`, update login/signup handlers to:

1. Store JWT token in localStorage:
```javascript
if (data.success && data.user && data.token) {
    localStorage.setItem('auth_token', data.token);
    localStorage.setItem('user', JSON.stringify(data.user));
    // ... rest of success handling
}
```

2. Add helper functions (see full guide):
- `updateAuthState(user)`
- `redirectToApp()`
- `checkAuthStatus()`

### 6. Update API Client

In `frontend/js/api-client.js`, add authentication headers:

```javascript
getAuthHeaders() {
    const headers = {
        'Content-Type': 'application/json'
    };
    
    if (window.authState && window.authState.getToken()) {
        headers['Authorization'] = `Bearer ${window.authState.getToken()}`;
    }
    
    return headers;
}
```

---

## Testing Checklist

- [ ] Login with email/password → stores token → redirects to dashboard
- [ ] Signup creates account → stores token → redirects to dashboard
- [ ] OAuth login → stores token → redirects to dashboard
- [ ] Access protected route without auth → redirects to login
- [ ] Access protected route with valid token → allows access
- [ ] Token expiration → redirects to login
- [ ] Logout → clears token → redirects to login

---

## Key Concepts

### Session Management
- **Flask Sessions**: Server-side state (OAuth callbacks, CSRF tokens)
- **JWT Tokens**: Stateless API authentication (stored in localStorage)
- **localStorage**: Client-side persistence (survives page reloads)

### Authentication Flow
1. User submits credentials → Backend validates → Returns JWT token
2. Frontend stores token in localStorage
3. Frontend includes token in API requests via `Authorization: Bearer <token>` header
4. Backend verifies token on each request
5. Token expires after 7 days → User must re-authenticate

### Protected Routes
- Routes in `PROTECTED_ROUTES` array require authentication
- Unauthenticated users redirected to `/login?redirect=<original_path>`
- Authenticated users redirected away from login/signup pages

---

## Security Notes

- ✅ Passwords hashed with bcrypt
- ✅ JWT tokens expire after 7 days
- ✅ CSRF protection for form submissions
- ✅ HttpOnly cookies for Flask sessions
- ⚠️ Set `SESSION_COOKIE_SECURE = True` in production (requires HTTPS)
- ⚠️ Implement rate limiting for production
- ⚠️ Add account lockout after failed login attempts

---

## Troubleshooting

### Token Not Stored
- Check browser console for errors
- Verify `localStorage` is available (not in incognito mode)
- Check API response includes `token` field

### Redirect Loop
- Check `auth-state.js` is loaded before `protected-routes.js`
- Verify `authState.init()` is called
- Check token verification endpoint `/api/auth/me` is working

### OAuth Not Working
- Verify OAuth callback stores token in Flask session
- Check `/api/auth/oauth/user` endpoint returns token
- Verify frontend fetches token after OAuth success

---

For complete implementation details, see `AUTHENTICATION_SETUP_GUIDE.md`
