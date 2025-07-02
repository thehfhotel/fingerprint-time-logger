# 🔄 Git Commit Strategy - Every Step Development

## 📋 Commit Rules & Guidelines

### **🎯 Core Principle**
**Commit at EVERY development step** to maintain granular history and enable easy rollbacks.

### **⚡ When to Commit**
1. **After each feature implementation** (even partial)
2. **After each bug fix** (however small)
3. **After each file creation/modification**
4. **After each configuration change**
5. **After each test creation/update**
6. **After each documentation update**
7. **Before and after major refactoring**
8. **After each database schema change**
9. **After each API endpoint addition/modification**
10. **After each troubleshooting session**

### **📝 Commit Message Format**

```
<emoji> <type>: <subject>

<optional body with bullet points>
- Detail 1
- Detail 2
- Detail 3

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

### **🎨 Commit Types & Emojis**

| Type | Emoji | Description | Example |
|------|-------|-------------|---------|
| **Feature** | ✨ | New feature implementation | `✨ feat: Add Thai name search functionality` |
| **Fix** | 🐛 | Bug fixes | `🐛 fix: Resolve calendar date formatting issue` |
| **Docs** | 📚 | Documentation updates | `📚 docs: Update API reference for roles endpoint` |
| **Style** | 💄 | Code style, formatting | `💄 style: Format attendance calendar template` |
| **Refactor** | ♻️ | Code refactoring | `♻️ refactor: Optimize database query performance` |
| **Test** | 🧪 | Test additions/updates | `🧪 test: Add unit tests for sync service` |
| **Config** | 🔧 | Configuration changes | `🔧 config: Update database connection settings` |
| **Database** | 🗄️ | Database schema changes | `🗄️ db: Add external sync fields to JobRole` |
| **API** | 🔌 | API endpoint changes | `🔌 api: Add employee role assignment endpoint` |
| **UI** | 🎨 | User interface updates | `🎨 ui: Improve attendance calendar layout` |
| **Performance** | ⚡ | Performance improvements | `⚡ perf: Optimize calendar data loading` |
| **Security** | 🔒 | Security improvements | `🔒 security: Add input validation to Thai names` |
| **Dependencies** | 📦 | Dependency updates | `📦 deps: Add aiohttp for external API calls` |
| **Cleanup** | 🧹 | Code cleanup | `🧹 cleanup: Remove unused import statements` |
| **Analytics** | 📊 | Analytics/reporting features | `📊 analytics: Add monthly attendance statistics` |
| **Troubleshoot** | 🔍 | Troubleshooting/debugging | `🔍 debug: Fix empty database state issue` |

### **🚀 Commit Workflow**

#### **Before Each Development Session:**
```bash
# 1. Check current status
git status

# 2. Create feature branch (optional for larger features)
git checkout -b feature/description

# 3. Pull latest changes
git pull origin master
```

#### **During Development (Every Step):**
```bash
# 1. Add changes
git add .

# 2. Commit with descriptive message
git commit -m "✨ feat: Add new feature component

- Implement core functionality
- Add input validation
- Update related tests

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"

# 3. Continue development...
```

#### **After Development Session:**
```bash
# 1. Final commit if needed
git add . && git commit -m "🧹 cleanup: Finalize feature implementation"

# 2. Push to remote
git push origin master

# 3. Optional: Create pull request for review
```

### **📋 Pre-Commit Checklist**

- [ ] **Code Quality**: No syntax errors or warnings
- [ ] **Formatting**: Code follows project style guidelines  
- [ ] **Tests**: Existing tests still pass
- [ ] **Documentation**: Updated if API/functionality changed
- [ ] **Dependencies**: New dependencies documented
- [ ] **Configuration**: Settings updated if needed
- [ ] **Database**: Schema changes documented
- [ ] **Backwards Compatibility**: No breaking changes without notice

### **🎯 Commit Granularity Examples**

#### **✅ Good Granular Commits:**
```
✨ feat: Add employee search functionality
🔧 config: Update API timeout settings  
🐛 fix: Resolve calendar date display bug
📚 docs: Update installation instructions
🧪 test: Add validation tests for Thai names
```

#### **❌ Avoid Large Commits:**
```
🔧 Massive update with multiple features, fixes, and changes
```

### **🔄 Recovery Strategy**

#### **Quick Rollback:**
```bash
# Rollback last commit (keep changes)
git reset --soft HEAD~1

# Rollback last commit (discard changes)  
git reset --hard HEAD~1

# Rollback to specific commit
git reset --hard <commit-hash>
```

#### **Feature Rollback:**
```bash
# Find commits for specific feature
git log --oneline --grep="feature-name"

# Revert specific commit
git revert <commit-hash>
```

### **📊 Commit History Benefits**

1. **🔍 Easy Debugging**: Identify when issues were introduced
2. **📈 Progress Tracking**: Clear development timeline  
3. **🔄 Safe Rollbacks**: Granular undo capabilities
4. **👥 Team Collaboration**: Clear change communication
5. **📚 Knowledge Base**: Commit messages as documentation
6. **🎯 Feature Isolation**: Easy to identify related changes
7. **🚀 Release Management**: Clear version history

### **🎨 Branch Strategy (Optional)**

For larger features, consider:
```bash
# Create feature branch
git checkout -b feature/attendance-calendar

# Work with frequent commits
git commit -m "✨ feat: Add calendar component structure"
git commit -m "🎨 ui: Style calendar grid layout"  
git commit -m "🔌 api: Connect calendar to attendance data"

# Merge back to master
git checkout master
git merge feature/attendance-calendar
git branch -d feature/attendance-calendar
```

---

## 🎯 **RULE ENFORCEMENT**

**Every code change, no matter how small, gets committed immediately with a descriptive message.**

This ensures:
- 📚 Complete development history
- 🔄 Easy rollback capabilities  
- 👥 Clear team communication
- 🎯 Granular change tracking
- 🚀 Continuous integration readiness