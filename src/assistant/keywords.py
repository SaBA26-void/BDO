"""Georgian keywords and patterns used to understand the employee's messages."""

import re

# Order matters: UNPAID wording contains the ANNUAL keyword "ანაზღაურებადი",
# and ANNUAL keywords are generic, so specific types are checked first.
LEAVE_TYPE_KEYWORDS = {
    "UNPAID": ["უანაზღაურებ", "არაანაზღაურებ", "ანაზღაურების გარეშე", "უხელფასო"],
    "SICK": ["ავადმყოფობ", "ბიულეტენ", "ექიმ", "ჯანმრთელობ", "ავად"],
    "STUDY": ["სასწავლო", "საგამოცდო", "გამოცდ", "უნივერსიტეტ", "ტრენინგ"],
    "BEREAVEMENT": ["გლოვ", "დაკრძალვ", "გარდაცვალ"],
    "PARENTAL": ["მშობლის", "დედობ", "მამობ", "დეკრეტ", "ბავშვის მოვლ", "შვილად აყვან"],
    "ANNUAL": ["ანაზღაურებადი", "წლიური", "ყოველწლიური", "ჩვეულებრივი", "კუთვნილი", "დასვენებ"],
}

BALANCE_KEYWORDS = [
    "ბალანს", "ნაშთ", "დამრჩა", "დამრჩენია", "მაქვს დარჩენილი", "დარჩენილი მაქვს",
]

# Explicit action phrasing only; a bare "შვებულება" is usually a policy question.
CREATE_KEYWORDS = [
    "მინდა შვებულება", "მინდა ავიღო", "ავიღო", "ავიღებ", "მოვითხოვ", "მოთხოვნის შექმნა",
    "დამიფორმე", "გამიფორმე", "გაფორმება", "დაარეგისტრირე", "დარეგისტრირება",
    "შვებულების აღება", "შვებულებაში გასვლა", "გავალ შვებულებაში", "მჭირდება შვებულება",
]
WANT_WORDS = ["მინდა", "მჭირდება"]
QUESTION_WORDS = {"რამდენი", "როგორ", "როდის", "რა", "სად", "ვის", "რატომ", "რომელი", "შეიძლება"}

CONFIRM_WORDS = {"კი", "დიახ"}
DECLINE_WORDS = {"არა", "არ მინდა", "გაუქმება", "გააუქმე"}

DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
EMPLOYEE_ALIAS_PATTERN = re.compile(r"EMP(\d{1,3})")
