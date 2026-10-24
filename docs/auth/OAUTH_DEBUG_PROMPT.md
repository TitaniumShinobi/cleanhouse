# OAuth Google Sign-In Debugging Prompt

Copy and paste this prompt into your other coding LLM application:

---

**Context:**
I'm working on a Flask + Vanilla JavaScript authentication system for CleanHouse. The Google OAuth "Continue with Google" button is not working in browser mode. The button is enabled (terms checkbox is checked), but clicking it doesn't redirect to Google OAuth.

**Current Setup:**
- Backend: Flask server running on `http://127.0.0.1:5000`
- Frontend: Vanilla JavaScript (no frameworks) in `frontend/js/auth.js`
- OAuth Endpoint: `/api/auth/oauth/google` (GET) - should redirect to Google OAuth
- Environment: Browser mode (not pywebview desktop app)
- GOOGLE_CLIENT_ID: Set in `.env` file and loaded correctly

**Error Messages from Browser Console:**

1. **Multiple TypeError errors:**
   ```
   Uncaught TypeError: Cannot read properties of undefined (reading 'api')
   at HTMLDocument.<anonymous> (auth.js:227:50)
   at HTMLDocument.<anonymous> (auth.js:246:50)
   at HTMLDocument.<anonymous> (auth.js:208:50)
   ```

2. **showOAuthLoading error:**
   ```
   Uncaught (in promise) TypeError: Cannot read properties of null (reading 'style')
   at showOAuthLoading (auth.js:643:33)
   at signInWithGoogle (auth.js:387:21)
   ```

3. **Console logs show:**
   ```
   [OAUTH] signInWithGoogle() called
   [OAUTH] IS_BROWSER: true
   [OAUTH] IS_PYWEBVIEW: undefined
   [OAUTH] Button disabled? false
   [CLICK] Google OAuth button clicked
   ```

**Code Structure:**

The `signInWithGoogle()` function in `frontend/js/auth.js`:
- Detects browser mode correctly (`IS_BROWSER: true`)
- Button is enabled (not disabled)
- Function is called when button is clicked
- Should redirect to `/api/auth/oauth/google` in browser mode
- But the redirect doesn't happen and `showOAuthLoading` throws an error

**Issues to Investigate:**

1. **TypeError: Cannot read properties of undefined (reading 'api')**
   - The code is trying to access `window.pywebview.api` even in browser mode
   - Lines 227, 246, 208 are accessing `window.pywebview.api` without checking if it exists
   - Need to add proper guards: `if (IS_PYWEBVIEW && window.pywebview?.api)`

2. **TypeError: Cannot read properties of null (reading 'style')**
   - `showOAuthLoading()` is trying to access `document.getElementById('loading-overlay')` 
   - This element doesn't exist on the signup page (only exists on login page)
   - Need to check if element exists before accessing `.style`

3. **OAuth Redirect Not Working**
   - The redirect code: `window.location.href = \`${window.location.origin}/api/auth/oauth/google\`;`
   - Should redirect to `http://127.0.0.1:5000/api/auth/oauth/google`
   - But nothing happens - no redirect, no network request visible
   - The error in `showOAuthLoading` might be preventing the redirect

**What I Need:**

1. **Fix the TypeError errors:**
   - Add proper null/undefined checks before accessing `window.pywebview.api`
   - Only access pywebview API when `IS_PYWEBVIEW` is true
   - Fix all instances where `window.pywebview.api` is accessed without guards

2. **Fix showOAuthLoading function:**
   - Check if `loading-overlay` element exists before accessing it
   - Handle case where element doesn't exist (signup page vs login page)
   - Don't throw errors if element is missing

3. **Ensure OAuth redirect works:**
   - Make sure the redirect happens even if `showOAuthLoading` has issues
   - Add error handling so redirect isn't blocked by other errors
   - Verify the redirect URL is correct

4. **Code locations to check:**
   - `frontend/js/auth.js` lines around 208, 227, 246 (pywebview.api access)
   - `frontend/js/auth.js` line 643 (showOAuthLoading function)
   - `frontend/js/auth.js` line 387+ (signInWithGoogle function)
   - Check for `loading-overlay` element in `frontend/signup.html` vs `frontend/login.html`

**Expected Behavior:**
1. User clicks "Continue with Google" button
2. `showOAuthLoading(true)` is called (should handle missing element gracefully)
3. Browser redirects to `/api/auth/oauth/google`
4. Flask backend redirects to Google OAuth URL
5. User completes OAuth in Google
6. Google redirects back to `/api/auth/oauth/callback`
7. User is authenticated and redirected to dashboard

**Current Behavior:**
1. User clicks "Continue with Google" button ✅
2. `showOAuthLoading(true)` throws error ❌
3. Redirect never happens ❌

**Files to Review:**
- `frontend/js/auth.js` - Main authentication JavaScript
- `frontend/signup.html` - Signup page HTML
- `frontend/login.html` - Login page HTML (has `loading-overlay` element)
- `backend/api/auth.py` - OAuth endpoint implementation

Please:
1. Identify all places where `window.pywebview.api` is accessed without proper guards
2. Fix `showOAuthLoading` to handle missing DOM elements
3. Ensure the OAuth redirect happens reliably
4. Add proper error handling so one error doesn't block the entire flow
5. Provide the corrected code with explanations

Thank you!

---

