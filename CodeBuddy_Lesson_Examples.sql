USE codebuddy;

UPDATE lessons
SET example_code = CONCAT(
'name = "Riya"   # Stores the name Riya', CHAR(10),
'print("Hello", name)   # Displays a greeting'
),
example_output = 'Hello Riya'
WHERE id = 1;

UPDATE lessons
SET example_code = CONCAT(
'name = "Aman"   # Stores the name', CHAR(10),
'age = 12   # Stores the age', CHAR(10),
'print(name)   # Displays the name', CHAR(10),
'print(age)   # Displays the age'
),
example_output = CONCAT('Aman', CHAR(10), '12')
WHERE id = 2;

UPDATE lessons
SET example_code = CONCAT(
'marks = 75   # Stores the marks', CHAR(10), CHAR(10),
'if marks >= 50:   # Checks if marks are 50 or more', CHAR(10),
'    print("You Passed!")   # Displays message if true', CHAR(10),
'else:   # Runs if condition is false', CHAR(10),
'    print("Try Again!")   # Displays message if false'
),
example_output = 'You Passed!'
WHERE id = 3;

UPDATE lessons
SET example_code = CONCAT(
'for i in range(5):   # Repeats the code 5 times', CHAR(10),
'    print("I Love Coding!")   # Displays the message'
),
example_output = CONCAT(
'I Love Coding!', CHAR(10),
'I Love Coding!', CHAR(10),
'I Love Coding!', CHAR(10),
'I Love Coding!', CHAR(10),
'I Love Coding!'
)
WHERE id = 4;

UPDATE lessons
SET example_code = CONCAT(
'def greet():   # Creates a function named greet', CHAR(10),
'    print("Hello, Young Coder!")   # Displays a greeting', CHAR(10),
CHAR(10),
'greet()   # Calls the function'
),
example_output = 'Hello, Young Coder!'
WHERE id = 5;