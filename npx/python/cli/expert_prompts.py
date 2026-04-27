"""Expert review prompts for code-review-expert integration.

Provides default prompts and output format templates for expert PR reviews.
"""

# Severity level guide for PR reviews
SEVERITY_GUIDE = """
## Severity Levels

| Level | Name | Description | Action |
|-------|------|-------------|--------|
| **P0** | Critical | Security vulnerability, data loss risk, correctness bug | Must block merge |
| **P1** | High | Logic error, significant SOLID violation, performance regression | Should fix before merge |
| **P2** | Medium | Code smell, maintainability concern, minor SOLID violation | Fix in this PR or create follow-up |
| **P3** | Low | Style, naming, minor suggestion | Optional improvement |
"""

# Default expert review prompt when --expert flag is used without a question
EXPERT_REVIEW_PROMPT = """Perform a comprehensive expert code review of this PR.

## Review Categories

Analyze the PR changes against these categories. Fetch the relevant checklist if you need detailed guidance:

1. **SOLID & Architecture** - Design principle violations, code smells
   - Fetch `checklists/solid-checklist.md` for detailed SOLID prompts
   
2. **Security & Reliability** - Vulnerabilities, auth gaps, race conditions
   - Fetch `checklists/security-checklist.md` for security patterns to check
   
3. **Code Quality** - Error handling, performance, boundary conditions
   - Fetch `checklists/code-quality-checklist.md` for quality patterns
   
4. **Removal Candidates** - Dead code, unused imports, deprecated patterns
   - Fetch `checklists/removal-plan.md` for removal planning template

## Instructions

1. First, understand the PR: read the diff, description, and any related files
2. Decide which categories are relevant based on the changes
3. Fetch the relevant checklist(s) for your analysis:
   - `FETCH_FILE:checklists/solid-checklist.md` for SOLID & Architecture
   - `FETCH_FILE:checklists/security-checklist.md` for Security & Reliability
   - `FETCH_FILE:checklists/code-quality-checklist.md` for Code Quality
   - `FETCH_FILE:checklists/removal-plan.md` for Removal Candidates
4. Apply the checklists to find issues
5. Classify each finding by severity (P0, P1, P2, P3)
6. Provide fix suggestions for P0 and P1 issues

## Severity Levels

- **P0 (Critical)**: Security vulnerability, data loss risk, correctness bug → MUST block merge
- **P1 (High)**: Logic error, significant SOLID violation, performance regression → Should fix before merge
- **P2 (Medium)**: Code smell, maintainability concern, minor SOLID violation → Fix in PR or follow-up
- **P3 (Low)**: Style, naming, minor suggestion → Optional improvement

## Required Output Format

Structure your review as follows:

```
## Code Review Summary

**Files reviewed**: X files, Y lines changed
**Overall assessment**: [APPROVE / REQUEST_CHANGES / COMMENT]

---

## Findings

### P0 - Critical
(none or list)

### P1 - High
- **[file:line]** Brief title
  - Description of issue
  - Suggested fix

### P2 - Medium
...

### P3 - Low
...

---

## Fix Suggestions (P0/P1 only)

### [Issue Title]
```language
// suggested code fix
```

---

## Additional Notes
(optional: areas not covered, recommended follow-up tests)
```
"""

# Output format template for parsing RLM responses
OUTPUT_FORMAT_TEMPLATE = """## Code Review Summary

**Files reviewed**: {files_count} files, {lines_changed} lines changed
**Overall assessment**: {assessment}

---

## Findings

### P0 - Critical
{p0_findings}

### P1 - High
{p1_findings}

### P2 - Medium
{p2_findings}

### P3 - Low
{p3_findings}

---

## Fix Suggestions

{fix_suggestions}

---

*AsyncReview Expert Review • {model}*
"""


def get_expert_prompt(user_question: str | None = None) -> str:
    """Get the appropriate prompt for expert review.
    
    Args:
        user_question: Optional user-provided question to append
        
    Returns:
        The full expert review prompt
    """
    if user_question:
        return f"{EXPERT_REVIEW_PROMPT}\n\n---\n\n**Additional User Question:** {user_question}"
    return EXPERT_REVIEW_PROMPT
