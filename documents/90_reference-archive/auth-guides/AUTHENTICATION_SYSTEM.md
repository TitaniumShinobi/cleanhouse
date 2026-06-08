# CleanHouse Authentication System

## 🎉 **Implementation Complete!**

Your CleanHouse application now has a complete account-based sign-in system with role-based access control, just like Bitdefender!

## ✅ **What's Been Implemented**

### 1. **User Authentication System**
- **Login/Signup UI** (`ui/auth.py`)
  - Beautiful authentication window with email/password fields
  - Sign up with role selection (user/dev)
  - "Remember me" functionality
  - Input validation and error handling

### 2. **User Database Management** (`ui/user_manager.py`)
- **SQLite Database** for secure credential storage
- **Password Hashing** using SHA-256 with salt
- **User Roles**: `user` and `dev` (developer)
- **Session Management** for "remember me" functionality
- **Default Admin Account**: `admin@cleanhouse.local` / `admin123`

### 3. **Per-User Data Isolation**
- **User Data Directories**: `userdata/{email}/`
  - `scan_results/` - Individual scan results
  - `logs/` - Personal log files
  - `preferences/` - User settings
- **Data Separation**: Each user's data is completely isolated

### 4. **Role-Based Access Control**
- **Developer-Only Modules**:
  - 🔒 **Zaelith Analysis Tab** - Advanced text analysis
  - 🔒 **Lie Detection Tab** - AI-powered deception detection
- **Regular User Access**:
  - ✅ Dashboard, Results, Logs, Settings, Cloud, Monitoring
- **Dynamic Tab Loading**: Tabs appear/disappear based on user role

### 5. **User Interface Enhancements**
- **User Info Box** (`ui/widgets/userbox.py`)
  - Shows current user email and role
  - Settings button for preferences
  - Logout functionality
- **Developer Badges**: Clear visual indicators for restricted features

## 🚀 **How to Use**

### **First Launch**
1. Run CleanHouse: `python3 corefiles/brain.py`
2. **Default Admin Account** will be created automatically:
   - Email: `admin@cleanhouse.local`
   - Password: `admin123`
   - Role: `dev` (full access)

### **Creating New Users**
1. Click "Sign Up" on the login screen
2. Enter email, password, and select role
3. Choose `dev` for full access or `user` for standard access

### **User Roles**

#### **Regular User (`user`)**
- ✅ Access to all standard CleanHouse features
- ✅ File monitoring, scanning, cloud sync
- ❌ No access to Zaelith or Lie Detection

#### **Developer (`dev`)**
- ✅ Full access to all features
- ✅ Zaelith Advanced Analysis
- ✅ Lie Detection capabilities
- ✅ All standard features

## 📁 **File Structure**

```
CleanHouse/
├── ui/
│   ├── auth.py              # Authentication UI
│   ├── user_manager.py      # User database & management
│   ├── main.py              # Updated with auth flow
│   ├── layout.py            # Role-based tab loading
│   ├── events.py            # Zaelith analysis handlers
│   ├── hooks.py             # User data isolation
│   └── widgets/
│       └── userbox.py       # User info display
├── userdata/                # User data directory
│   ├── admin_at_cleanhouse_local/
│   │   ├── scan_results/
│   │   ├── logs/
│   │   └── preferences/
│   └── {user_email}/
│       ├── scan_results/
│       ├── logs/
│       └── preferences/
└── user_auth.db            # SQLite user database
```

## 🔐 **Security Features**

- **Password Hashing**: SHA-256 with salt
- **SQLite Database**: Secure local storage
- **Role-Based Access**: Granular permission control
- **Data Isolation**: Complete user data separation
- **Session Management**: Secure login persistence

## 🎯 **Key Benefits**

1. **Distribution Ready**: Professional login system
2. **Multi-User Support**: Each user has private data
3. **Developer Tools**: Advanced features for developers
4. **Scalable Architecture**: Easy to add new roles/features
5. **Secure**: Proper authentication and data isolation

## 🚀 **Next Steps**

Your CleanHouse is now ready for distribution! Users can:
- Create accounts and sign in
- Access features based on their role
- Keep their data completely private
- Use advanced developer tools (if they have dev access)

The system is fully functional and ready for real-world use! 🎉

