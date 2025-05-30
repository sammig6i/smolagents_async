# coding=utf-8
# Copyright 2024 HuggingFace Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import ast
import types
from contextlib import nullcontext as does_not_raise
from textwrap import dedent
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from smolagents.default_tools import BASE_PYTHON_TOOLS, FinalAnswerTool
from smolagents.local_python_executor import (
    DANGEROUS_FUNCTIONS,
    DANGEROUS_MODULES,
    InterpreterError,
    LocalPythonExecutor,
    PrintContainer,
    check_import_authorized,
    evaluate_boolop,
    evaluate_condition,
    evaluate_delete,
    await evaluate_python_code,
    fix_final_answer_code,
    get_safe_module,
)


# Fake function we will use as tool
def add_two(x):
    return x + 2


class TestEvaluatePythonCode:
    def assertDictEqualNoPrint(self, dict1, dict2):
        assert {k: v for k, v in dict1.items() if k != "_print_outputs"} == {
            k: v for k, v in dict2.items() if k != "_print_outputs"
        }

    async def test_evaluate_assign(self):
        code = "x = 3"
        state = {}
        result, _ = await evaluate_python_code(code, {}, state=state)
        assert result == 3
        self.assertDictEqualNoPrint(state, {"x": 3, "_operations_count": {"counter": 2}})

        code = "x = y"
        state = {"y": 5}
        result, _ = await evaluate_python_code(code, {}, state=state)
        # evaluate returns the value of the last assignment.
        assert result == 5
        self.assertDictEqualNoPrint(state, {"x": 5, "y": 5, "_operations_count": {"counter": 2}})

        code = "a=1;b=None"
        result, _ = await evaluate_python_code(code, {}, state={})
        # evaluate returns the value of the last assignment.
        assert result is None

    async def test_assignment_cannot_overwrite_tool(self):
        code = "print = '3'"
        with pytest.raises(InterpreterError) as e:
            await evaluate_python_code(code, {"print": print}, state={})
        assert "Cannot assign to name 'print': doing this would erase the existing tool!" in str(e)

    async def test_subscript_call(self):
        code = """def foo(x,y):return x*y\n\ndef boo(y):\n\treturn y**3\nfun = [foo, boo]\nresult_foo = fun[0](4,2)\nresult_boo = fun[1](4)"""
        state = {}
        result, _ = await evaluate_python_code(code, BASE_PYTHON_TOOLS, state=state)
        assert result == 64
        assert state["result_foo"] == 8
        assert state["result_boo"] == 64

    async def test_evaluate_call(self):
        code = "y = add_two(x)"
        state = {"x": 3}
        result, _ = await evaluate_python_code(code, {"add_two": add_two}, state=state)
        assert result == 5
        self.assertDictEqualNoPrint(state, {"x": 3, "y": 5, "_operations_count": {"counter": 3}})

        # Should not work without the tool
        with pytest.raises(InterpreterError) as e:
            await evaluate_python_code(code, {}, state=state)
        assert "tried to execute add_two" in str(e.value)

    async def test_evaluate_constant(self):
        code = "x = 3"
        state = {}
        result, _ = await evaluate_python_code(code, {}, state=state)
        assert result == 3
        self.assertDictEqualNoPrint(state, {"x": 3, "_operations_count": {"counter": 2}})

    async def test_evaluate_dict(self):
        code = "test_dict = {'x': x, 'y': add_two(x)}"
        state = {"x": 3}
        result, _ = await evaluate_python_code(code, {"add_two": add_two}, state=state)
        self.assertDictEqual(result, {"x": 3, "y": 5})
        self.assertDictEqualNoPrint(state, {"x": 3, "test_dict": {"x": 3, "y": 5}, "_operations_count": 7})

    async def test_evaluate_expression(self):
        code = "x = 3\ny = 5"
        state = {}
        result, _ = await evaluate_python_code(code, {}, state=state)
        # evaluate returns the value of the last assignment.
        assert result == 5
        self.assertDictEqualNoPrint(state, {"x": 3, "y": 5, "_operations_count": {"counter": 4}})

    async def test_evaluate_f_string(self):
        code = "text = f'This is x: {x}.'"
        state = {"x": 3}
        result, _ = await evaluate_python_code(code, {}, state=state)
        # evaluate returns the value of the last assignment.
        assert result == "This is x: 3."
        self.assertDictEqualNoPrint(state, {"x": 3, "text": "This is x: 3.", "_operations_count": 6})

    async def test_evaluate_if(self):
        code = "if x <= 3:\n    y = 2\nelse:\n    y = 5"
        state = {"x": 3}
        result, _ = await evaluate_python_code(code, {}, state=state)
        # evaluate returns the value of the last assignment.
        assert result == 2
        self.assertDictEqualNoPrint(state, {"x": 3, "y": 2, "_operations_count": {"counter": 6}})

        state = {"x": 8}
        result, _ = await evaluate_python_code(code, {}, state=state)
        # evaluate returns the value of the last assignment.
        assert result == 5
        self.assertDictEqualNoPrint(state, {"x": 8, "y": 5, "_operations_count": {"counter": 6}})

    async def test_evaluate_list(self):
        code = "test_list = [x, add_two(x)]"
        state = {"x": 3}
        result, _ = await evaluate_python_code(code, {"add_two": add_two}, state=state)
        self.assertListEqual(result, [3, 5])
        self.assertDictEqualNoPrint(state, {"x": 3, "test_list": [3, 5], "_operations_count": 5})

    async def test_evaluate_name(self):
        code = "y = x"
        state = {"x": 3}
        result, _ = await evaluate_python_code(code, {}, state=state)
        assert result == 3
        self.assertDictEqualNoPrint(state, {"x": 3, "y": 3, "_operations_count": {"counter": 2}})

    async def test_evaluate_subscript(self):
        code = "test_list = [x, add_two(x)]\ntest_list[1]"
        state = {"x": 3}
        result, _ = await evaluate_python_code(code, {"add_two": add_two}, state=state)
        assert result == 5
        self.assertDictEqualNoPrint(state, {"x": 3, "test_list": [3, 5], "_operations_count": {"counter": 9}})

        code = "test_dict = {'x': x, 'y': add_two(x)}\ntest_dict['y']"
        state = {"x": 3}
        result, _ = await evaluate_python_code(code, {"add_two": add_two}, state=state)
        assert result == 5
        self.assertDictEqualNoPrint(
            state, {"x": 3, "test_dict": {"x": 3, "y": 5}, "_operations_count": {"counter": 11}}
        )

        code = "vendor = {'revenue': 31000, 'rent': 50312}; vendor['ratio'] = round(vendor['revenue'] / vendor['rent'], 2)"
        state = {}
        await evaluate_python_code(code, {"min": min, "print": print, "round": round}, state=state)
        assert state["vendor"] == {"revenue": 31000, "rent": 50312, "ratio": 0.62}

    async def test_subscript_string_with_string_index_raises_appropriate_error(self):
        code = """
search_results = "[{'title': 'Paris, Ville de Paris, France Weather Forecast | AccuWeather', 'href': 'https://www.accuweather.com/en/fr/paris/623/weather-forecast/623', 'body': 'Get the latest weather forecast for Paris, Ville de Paris, France , including hourly, daily, and 10-day outlooks. AccuWeather provides you with reliable and accurate information on temperature ...'}]"
for result in search_results:
    if 'current' in result['title'].lower() or 'temperature' in result['title'].lower():
        current_weather_url = result['href']
        print(current_weather_url)
        break"""
        with pytest.raises(InterpreterError) as e:
            await evaluate_python_code(code, BASE_PYTHON_TOOLS, state={})
            assert "You're trying to subscript a string with a string index" in e

    async def test_evaluate_for(self):
        code = "x = 0\nfor i in range(3):\n    x = i"
        state = {}
        result, _ = await evaluate_python_code(code, {"range": range}, state=state)
        assert result == 2
        self.assertDictEqualNoPrint(state, {"x": 2, "i": 2, "_operations_count": {"counter": 11}})

    async def test_evaluate_binop(self):
        code = "y + x"
        state = {"x": 3, "y": 6}
        result, _ = await evaluate_python_code(code, {}, state=state)
        assert result == 9
        self.assertDictEqualNoPrint(state, {"x": 3, "y": 6, "_operations_count": {"counter": 4}})

    async def test_recursive_function(self):
        code = """
def recur_fibo(n):
    if n <= 1:
        return n
    else:
        return(recur_fibo(n-1) + recur_fibo(n-2))
recur_fibo(6)"""
        result, _ = await evaluate_python_code(code, {}, state={})
        assert result == 8

    async def test_evaluate_string_methods(self):
        code = "'hello'.replace('h', 'o').split('e')"
        result, _ = await evaluate_python_code(code, {}, state={})
        assert result == ["o", "llo"]

    async def test_evaluate_slicing(self):
        code = "'hello'[1:3][::-1]"
        result, _ = await evaluate_python_code(code, {}, state={})
        assert result == "le"

    async def test_access_attributes(self):
        code = "integer = 1\nobj_class = integer.__class__\nobj_class"
        result, _ = await evaluate_python_code(code, {}, state={})
        assert result is int

    async def test_list_comprehension(self):
        code = "sentence = 'THESEAGULL43'\nmeaningful_sentence = '-'.join([char.lower() for char in sentence if char.isalpha()])"
        result, _ = await evaluate_python_code(code, {}, state={})
        assert result == "t-h-e-s-e-a-g-u-l-l"

    async def test_string_indexing(self):
        code = """text_block = [
    "THESE",
    "AGULL"
]
sentence = ""
for block in text_block:
    for col in range(len(text_block[0])):
        sentence += block[col]
        """
        result, _ = await evaluate_python_code(code, {"len": len, "range": range}, state={})
        assert result == "THESEAGULL"

    async def test_tuples(self):
        code = "x = (1, 2, 3)\nx[1]"
        result, _ = await evaluate_python_code(code, {}, state={})
        assert result == 2

        code = """
digits, i = [1, 2, 3], 1
digits[i], digits[i + 1] = digits[i + 1], digits[i]"""
        await evaluate_python_code(code, {"range": range, "print": print, "int": int}, {})

        code = """
def calculate_isbn_10_check_digit(number):
    total = sum((10 - i) * int(digit) for i, digit in enumerate(number))
    remainder = total % 11
    check_digit = 11 - remainder
    if check_digit == 10:
        return 'X'
    elif check_digit == 11:
        return '0'
    else:
        return str(check_digit)

# Given 9-digit numbers
numbers = [
    "478225952",
    "643485613",
    "739394228",
    "291726859",
    "875262394",
    "542617795",
    "031810713",
    "957007669",
    "871467426"
]

# Calculate check digits for each number
check_digits = [calculate_isbn_10_check_digit(number) for number in numbers]
print(check_digits)
"""
        state = {}
        await evaluate_python_code(
            code,
            {
                "range": range,
                "print": print,
                "sum": sum,
                "enumerate": enumerate,
                "int": int,
                "str": str,
            },
            state,
        )

    async def test_listcomp(self):
        code = "x = [i for i in range(3)]"
        result, _ = await evaluate_python_code(code, {"range": range}, state={})
        assert result == [0, 1, 2]

    async def test_break_continue(self):
        code = "for i in range(10):\n    if i == 5:\n        break\ni"
        result, _ = await evaluate_python_code(code, {"range": range}, state={})
        assert result == 5

        code = "for i in range(10):\n    if i == 5:\n        continue\ni"
        result, _ = await evaluate_python_code(code, {"range": range}, state={})
        assert result == 9

    async def test_call_int(self):
        code = "import math\nstr(math.ceil(149))"
        result, _ = await evaluate_python_code(code, {"str": lambda x: str(x)}, state={})
        assert result == "149"

    async def test_lambda(self):
        code = "f = lambda x: x + 2\nf(3)"
        result, _ = await evaluate_python_code(code, {}, state={})
        assert result == 5

    async def test_dictcomp(self):
        code = "x = {i: i**2 for i in range(3)}"
        result, _ = await evaluate_python_code(code, {"range": range}, state={})
        assert result == {0: 0, 1: 1, 2: 4}

        code = "{num: name for num, name in {101: 'a', 102: 'b'}.items() if name not in ['a']}"
        result, _ = await evaluate_python_code(code, {"print": print}, state={}, authorized_imports=["pandas"])
        assert result == {102: "b"}

        code = """
shifts = {'A': ('6:45', '8:00'), 'B': ('10:00', '11:45')}
shift_minutes = {worker: ('a', 'b') for worker, (start, end) in shifts.items()}
"""
        result, _ = await evaluate_python_code(code, {}, state={})
        assert result == {"A": ("a", "b"), "B": ("a", "b")}

    async def test_tuple_assignment(self):
        code = "a, b = 0, 1\nb"
        result, _ = await evaluate_python_code(code, BASE_PYTHON_TOOLS, state={})
        assert result == 1

    async def test_while(self):
        code = "i = 0\nwhile i < 3:\n    i += 1\ni"
        result, _ = await evaluate_python_code(code, BASE_PYTHON_TOOLS, state={})
        assert result == 3

        # test infinite loop
        code = "i = 0\nwhile i < 3:\n    i -= 1\ni"
        with pytest.raises(InterpreterError) as e:
            await evaluate_python_code(code, BASE_PYTHON_TOOLS, state={})
        assert "iterations in While loop exceeded" in str(e)

        # test lazy evaluation
        code = dedent(
            """
            house_positions = [0, 7, 10, 15, 18, 22, 22]
            i, n, loc = 0, 7, 30
            while i < n and house_positions[i] <= loc:
                i += 1
            """
        )
        state = {}
        await evaluate_python_code(code, BASE_PYTHON_TOOLS, state=state)

    async def test_generator(self):
        code = "a = [1, 2, 3, 4, 5]; b = (i**2 for i in a); list(b)"
        result, _ = await evaluate_python_code(code, BASE_PYTHON_TOOLS, state={})
        assert result == [1, 4, 9, 16, 25]

    async def test_boolops(self):
        code = """if (not (a > b and a > c)) or d > e:
    best_city = "Brooklyn"
else:
    best_city = "Manhattan"
    best_city
    """
        result, _ = await evaluate_python_code(code, BASE_PYTHON_TOOLS, state={"a": 1, "b": 2, "c": 3, "d": 4, "e": 5})
        assert result == "Brooklyn"

        code = """if d > e and a < b:
    best_city = "Brooklyn"
elif d < e and a < b:
    best_city = "Sacramento"
else:
    best_city = "Manhattan"
    best_city
    """
        result, _ = await evaluate_python_code(code, BASE_PYTHON_TOOLS, state={"a": 1, "b": 2, "c": 3, "d": 4, "e": 5})
        assert result == "Sacramento"

    async def test_if_conditions(self):
        code = """char='a'
if char.isalpha():
    print('2')"""
        state = {}
        await evaluate_python_code(code, BASE_PYTHON_TOOLS, state=state)
        assert state["_print_outputs"].value == "2\n"

    async def test_imports(self):
        code = "import math\nmath.sqrt(4)"
        result, _ = await evaluate_python_code(code, BASE_PYTHON_TOOLS, state={})
        assert result == 2.0

        code = "from random import choice, seed\nseed(12)\nchoice(['win', 'lose', 'draw'])"
        result, _ = await evaluate_python_code(code, BASE_PYTHON_TOOLS, state={})
        assert result == "lose"

        code = "import time, re\ntime.sleep(0.1)"
        result, _ = await evaluate_python_code(code, BASE_PYTHON_TOOLS, state={})
        assert result is None

        code = "from queue import Queue\nq = Queue()\nq.put(1)\nq.get()"
        result, _ = await evaluate_python_code(code, BASE_PYTHON_TOOLS, state={})
        assert result == 1

        code = "import itertools\nlist(itertools.islice(range(10), 3))"
        result, _ = await evaluate_python_code(code, BASE_PYTHON_TOOLS, state={})
        assert result == [0, 1, 2]

        code = "import re\nre.search('a', 'abc').group()"
        result, _ = await evaluate_python_code(code, BASE_PYTHON_TOOLS, state={})
        assert result == "a"

        code = "import stat\nstat.S_ISREG(0o100644)"
        result, _ = await evaluate_python_code(code, BASE_PYTHON_TOOLS, state={})
        assert result

        code = "import statistics\nstatistics.mean([1, 2, 3, 4, 4])"
        result, _ = await evaluate_python_code(code, BASE_PYTHON_TOOLS, state={})
        assert result == 2.8

        code = "import unicodedata\nunicodedata.name('A')"
        result, _ = await evaluate_python_code(code, BASE_PYTHON_TOOLS, state={})
        assert result == "LATIN CAPITAL LETTER A"

        # Test submodules are handled properly, thus not raising error
        code = "import numpy.random as rd\nrng = rd.default_rng(12345)\nrng.random()"
        result, _ = await evaluate_python_code(code, BASE_PYTHON_TOOLS, state={}, authorized_imports=["numpy"])

        code = "from numpy.random import default_rng as d_rng\nrng = d_rng(12345)\nrng.random()"
        result, _ = await evaluate_python_code(code, BASE_PYTHON_TOOLS, state={}, authorized_imports=["numpy"])

    async def test_additional_imports(self):
        code = "import numpy as np"
        await evaluate_python_code(code, authorized_imports=["numpy"], state={})

        code = "import numpy.random as rd"
        await evaluate_python_code(code, authorized_imports=["numpy.random"], state={})
        await evaluate_python_code(code, authorized_imports=["numpy"], state={})
        await evaluate_python_code(code, authorized_imports=["*"], state={})
        with pytest.raises(InterpreterError):
            await evaluate_python_code(code, authorized_imports=["random"], state={})

    async def test_multiple_comparators(self):
        code = "0 <= -1 < 4 and 0 <= -5 < 4"
        result, _ = await evaluate_python_code(code, BASE_PYTHON_TOOLS, state={})
        assert not result

        code = "0 <= 1 < 4 and 0 <= -5 < 4"
        result, _ = await evaluate_python_code(code, BASE_PYTHON_TOOLS, state={})
        assert not result

        code = "0 <= 4 < 4 and 0 <= 3 < 4"
        result, _ = await evaluate_python_code(code, BASE_PYTHON_TOOLS, state={})
        assert not result

        code = "0 <= 3 < 4 and 0 <= 3 < 4"
        result, _ = await evaluate_python_code(code, BASE_PYTHON_TOOLS, state={})
        assert result

    async def test_print_output(self):
        code = "print('Hello world!')\nprint('Ok no one cares')"
        state = {}
        result, _ = await evaluate_python_code(code, BASE_PYTHON_TOOLS, state=state)
        assert result is None
        assert state["_print_outputs"].value == "Hello world!\nOk no one cares\n"

        # Test print in function (state copy)
        code = """
print("1")
def function():
    print("2")
function()"""
        state = {}
        await evaluate_python_code(code, {"print": print}, state=state)
        assert state["_print_outputs"].value == "1\n2\n"

        # Test print in list comprehension (state copy)
        code = """
print("1")
def function():
    print("2")
[function() for i in range(10)]"""
        state = {}
        await evaluate_python_code(code, {"print": print, "range": range}, state=state)
        assert state["_print_outputs"].value == "1\n2\n2\n2\n2\n2\n2\n2\n2\n2\n2\n"

    async def test_tuple_target_in_iterator(self):
        code = "for a, b in [('Ralf Weikert', 'Austria'), ('Samuel Seungwon Lee', 'South Korea')]:res = a.split()[0]"
        result, _ = await evaluate_python_code(code, BASE_PYTHON_TOOLS, state={})
        assert result == "Samuel"

    async def test_classes(self):
        code = """
class Animal:
    species = "Generic Animal"

    def __init__(self, name, age):
        self.name = name
        self.age = age

    def sound(self):
        return "The animal makes a sound."

    def __str__(self):
        return f"{self.name}, {self.age} years old"

class Dog(Animal):
    species = "Canine"

    def __init__(self, name, age, breed):
        super().__init__(name, age)
        self.breed = breed

    def sound(self):
        return "The dog barks."

    def __str__(self):
        return f"{self.name}, {self.age} years old, {self.breed}"

class Cat(Animal):
    def sound(self):
        return "The cat meows."

    def __str__(self):
        return f"{self.name}, {self.age} years old, {self.species}"


# Testing multiple instances
dog1 = Dog("Fido", 3, "Labrador")
dog2 = Dog("Buddy", 5, "Golden Retriever")

# Testing method with built-in function
animals = [dog1, dog2, Cat("Whiskers", 2)]
num_animals = len(animals)

# Testing exceptions in methods
class ExceptionTest:
    def method_that_raises(self):
        raise ValueError("An error occurred")

try:
    exc_test = ExceptionTest()
    exc_test.method_that_raises()
except ValueError as e:
    exception_message = str(e)


# Collecting results
dog1_sound = dog1.sound()
dog1_str = str(dog1)
dog2_sound = dog2.sound()
dog2_str = str(dog2)
cat = Cat("Whiskers", 2)
cat_sound = cat.sound()
cat_str = str(cat)
    """
        state = {}
        await evaluate_python_code(
            code,
            {"print": print, "len": len, "super": super, "str": str, "sum": sum},
            state=state,
        )

        # Assert results
        assert state["dog1_sound"] == "The dog barks."
        assert state["dog1_str"] == "Fido, 3 years old, Labrador"
        assert state["dog2_sound"] == "The dog barks."
        assert state["dog2_str"] == "Buddy, 5 years old, Golden Retriever"
        assert state["cat_sound"] == "The cat meows."
        assert state["cat_str"] == "Whiskers, 2 years old, Generic Animal"
        assert state["num_animals"] == 3
        assert state["exception_message"] == "An error occurred"

    async def test_variable_args(self):
        code = """
def var_args_method(self, *args, **kwargs):
    return sum(args) + sum(kwargs.values())

var_args_method(1, 2, 3, x=4, y=5)
"""
        state = {}
        result, _ = await evaluate_python_code(code, {"sum": sum}, state=state)
        assert result == 15

    async def test_exceptions(self):
        code = """
def method_that_raises(self):
    raise ValueError("An error occurred")

try:
    method_that_raises()
except ValueError as e:
    exception_message = str(e)
    """
        state = {}
        await evaluate_python_code(
            code,
            {"print": print, "len": len, "super": super, "str": str, "sum": sum},
            state=state,
        )
        assert state["exception_message"] == "An error occurred"

    async def test_print(self):
        code = "print(min([1, 2, 3]))"
        state = {}
        await evaluate_python_code(code, {"min": min, "print": print}, state=state)
        assert state["_print_outputs"].value == "1\n"

    async def test_types_as_objects(self):
        code = "type_a = float(2); type_b = str; type_c = int"
        state = {}
        result, is_final_answer = await evaluate_python_code(code, {"float": float, "str": str, "int": int}, state=state)
        assert result is int

    async def test_tuple_id(self):
        code = """
food_items = {"apple": 2, "banana": 3, "orange": 1, "pear": 1}
unique_food_items = [item for item, count in food_item_counts.items() if count == 1]
"""
        state = {}
        result, is_final_answer = await evaluate_python_code(code, {}, state=state)
        assert result == ["orange", "pear"]

    async def test_nonsimple_augassign(self):
        code = """
counts_dict = {'a': 0}
counts_dict['a'] += 1
counts_list = [1, 2, 3]
counts_list += [4, 5, 6]

class Counter:
    def __init__(self):
        self.count = 0

a = Counter()
a.count += 1
"""
        state = {}
        await evaluate_python_code(code, {}, state=state)
        assert state["counts_dict"] == {"a": 1}
        assert state["counts_list"] == [1, 2, 3, 4, 5, 6]
        assert state["a"].count == 1

    async def test_adding_int_to_list_raises_error(self):
        code = """
counts = [1, 2, 3]
counts += 1"""
        with pytest.raises(InterpreterError) as e:
            await evaluate_python_code(code, BASE_PYTHON_TOOLS, state={})
        assert "Cannot add non-list value 1 to a list." in str(e)

    async def test_error_highlights_correct_line_of_code(self):
        code = """a = 1
b = 2

counts = [1, 2, 3]
counts += 1
b += 1"""
        with pytest.raises(InterpreterError) as e:
            await evaluate_python_code(code, BASE_PYTHON_TOOLS, state={})
        assert "Code execution failed at line 'counts += 1" in str(e)

    async def test_error_type_returned_in_function_call(self):
        code = """def error_function():
    raise ValueError("error")

error_function()"""
        with pytest.raises(InterpreterError) as e:
            await evaluate_python_code(code)
        assert "error" in str(e)
        assert "ValueError" in str(e)

    async def test_assert(self):
        code = """
assert 1 == 1
assert 1 == 2
"""
        with pytest.raises(InterpreterError) as e:
            await evaluate_python_code(code, BASE_PYTHON_TOOLS, state={})
        assert "1 == 2" in str(e) and "1 == 1" not in str(e)

    async def test_with_context_manager(self):
        code = """
class SimpleLock:
    def __init__(self):
        self.locked = False

    def __enter__(self):
        self.locked = True
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.locked = False

lock = SimpleLock()

with lock as l:
    assert l.locked == True

assert lock.locked == False
    """
        state = {}
        tools = {}
        await evaluate_python_code(code, tools, state=state)

    async def test_default_arg_in_function(self):
        code = """
def f(a, b=333, n=1000):
    return b + n
n = f(1, n=667)
"""
        res, is_final_answer = await evaluate_python_code(code, {}, {})
        assert res == 1000
        assert not is_final_answer

    async def test_set(self):
        code = """
S1 = {'a', 'b', 'c'}
S2 = {'b', 'c', 'd'}
S3 = S1.difference(S2)
S4 = S1.intersection(S2)
"""
        state = {}
        await evaluate_python_code(code, {}, state=state)
        assert state["S3"] == {"a"}
        assert state["S4"] == {"b", "c"}

    async def test_break(self):
        code = """
i = 0

while True:
    i+= 1
    if i==3:
        break

i"""
        result, is_final_answer = await evaluate_python_code(code, {"print": print, "round": round}, state={})
        assert result == 3
        assert not is_final_answer

    async def test_return(self):
        # test early returns
        code = """
def add_one(n, shift):
    if True:
        return n + shift
    return n

add_one(1, 1)
"""
        state = {}
        result, is_final_answer = await evaluate_python_code(
            code, {"print": print, "range": range, "ord": ord, "chr": chr}, state=state
        )
        assert result == 2

        # test returning None
        code = """
def returns_none(a):
    return

returns_none(1)
"""
        state = {}
        result, is_final_answer = await evaluate_python_code(
            code, {"print": print, "range": range, "ord": ord, "chr": chr}, state=state
        )
        assert result is None

    async def test_nested_for_loop(self):
        code = """
all_res = []
for i in range(10):
    subres = []
    for j in range(i):
        subres.append(j)
    all_res.append(subres)

out = [i for sublist in all_res for i in sublist]
out[:10]
"""
        state = {}
        result, is_final_answer = await evaluate_python_code(code, {"print": print, "range": range}, state=state)
        assert result == [0, 0, 1, 0, 1, 2, 0, 1, 2, 3]

    async def test_pandas(self):
        code = """
import pandas as pd

df = pd.DataFrame.from_dict({'SetCount': ['5', '4', '5'], 'Quantity': [1, 0, -1]})

df['SetCount'] = pd.to_numeric(df['SetCount'], errors='coerce')

parts_with_5_set_count = df[df['SetCount'] == 5.0]
parts_with_5_set_count[['Quantity', 'SetCount']].values[1]
"""
        state = {}
        result, _ = await evaluate_python_code(code, {}, state=state, authorized_imports=["pandas"])
        assert np.array_equal(result, [-1, 5])

        code = """
import pandas as pd

df = pd.DataFrame.from_dict({"AtomicNumber": [111, 104, 105], "ok": [0, 1, 2]})

# Filter the DataFrame to get only the rows with outdated atomic numbers
filtered_df = df.loc[df['AtomicNumber'].isin([104])]
"""
        result, _ = await evaluate_python_code(code, {"print": print}, state={}, authorized_imports=["pandas"])
        assert np.array_equal(result.values[0], [104, 1])

        # Test groupby
        code = """import pandas as pd
data = pd.DataFrame.from_dict([
    {"Pclass": 1, "Survived": 1},
    {"Pclass": 2, "Survived": 0},
    {"Pclass": 2, "Survived": 1}
])
survival_rate_by_class = data.groupby('Pclass')['Survived'].mean()
"""
        result, _ = await evaluate_python_code(code, {}, state={}, authorized_imports=["pandas"])
        assert result.values[1] == 0.5

        # Test loc and iloc
        code = """import pandas as pd
data = pd.DataFrame.from_dict([
    {"Pclass": 1, "Survived": 1},
    {"Pclass": 2, "Survived": 0},
    {"Pclass": 2, "Survived": 1}
])
survival_rate_biased = data.loc[data['Survived']==1]['Survived'].mean()
survival_rate_biased = data.loc[data['Survived']==1]['Survived'].mean()
survival_rate_sorted = data.sort_values(by='Survived', ascending=False).iloc[0]
"""
        result, _ = await evaluate_python_code(code, {}, state={}, authorized_imports=["pandas"])

    async def test_starred(self):
        code = """
from math import radians, sin, cos, sqrt, atan2

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000  # Radius of the Earth in meters
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    distance = R * c
    return distance

coords_geneva = (46.1978, 6.1342)
coords_barcelona = (41.3869, 2.1660)

distance_geneva_barcelona = haversine(*coords_geneva, *coords_barcelona)
"""
        result, _ = await evaluate_python_code(code, {"print": print, "map": map}, state={}, authorized_imports=["math"])
        assert round(result, 1) == 622395.4

    async def test_for(self):
        code = """
shifts = {
    "Worker A": ("6:45 pm", "8:00 pm"),
    "Worker B": ("10:00 am", "11:45 am")
}

shift_intervals = {}
for worker, (start, end) in shifts.items():
    shift_intervals[worker] = end
shift_intervals
"""
        result, _ = await evaluate_python_code(code, {"print": print, "map": map}, state={})
        assert result == {"Worker A": "8:00 pm", "Worker B": "11:45 am"}

    async def test_syntax_error_points_error(self):
        code = "a = ;"
        with pytest.raises(InterpreterError) as e:
            await evaluate_python_code(code)
        assert "SyntaxError" in str(e)
        assert "     ^" in str(e)

    async def test_fix_final_answer_code(self):
        test_cases = [
            (
                "final_answer = 3.21\nfinal_answer(final_answer)",
                "final_answer_variable = 3.21\nfinal_answer(final_answer_variable)",
            ),
            (
                "x = final_answer(5)\nfinal_answer = x + 1\nfinal_answer(final_answer)",
                "x = final_answer(5)\nfinal_answer_variable = x + 1\nfinal_answer(final_answer_variable)",
            ),
            (
                "def func():\n    final_answer = 42\n    return final_answer(final_answer)",
                "def func():\n    final_answer_variable = 42\n    return final_answer(final_answer_variable)",
            ),
            (
                "final_answer(5)  # Should not change function calls",
                "final_answer(5)  # Should not change function calls",
            ),
            (
                "obj.final_answer = 5  # Should not change object attributes",
                "obj.final_answer = 5  # Should not change object attributes",
            ),
            (
                "final_answer=3.21;final_answer(final_answer)",
                "final_answer_variable=3.21;final_answer(final_answer_variable)",
            ),
        ]

        for i, (input_code, expected) in enumerate(test_cases, 1):
            result = fix_final_answer_code(input_code)
            assert result == expected, f"""
    Test case {i} failed:
    Input:    {input_code}
    Expected: {expected}
    Got:      {result}
    """

    async def test_dangerous_subpackage_access_blocked(self):
        # Direct imports with dangerous patterns should fail
        code = "import random._os"
        with pytest.raises(InterpreterError):
            await evaluate_python_code(code)

        # Import of whitelisted modules should succeed but dangerous submodules should not exist
        code = "import random;random._os.system('echo bad command passed')"
        with pytest.raises(InterpreterError) as e:
            await evaluate_python_code(code)
        assert "AttributeError: module 'random' has no attribute '_os'" in str(e)

        code = "import doctest;doctest.inspect.os.system('echo bad command passed')"
        with pytest.raises(InterpreterError):
            await evaluate_python_code(code, authorized_imports=["doctest"])

    async def test_close_matches_subscript(self):
        code = 'capitals = {"Czech Republic": "Prague", "Monaco": "Monaco", "Bhutan": "Thimphu"};capitals["Butan"]'
        with pytest.raises(Exception) as e:
            await evaluate_python_code(code)
        assert "Maybe you meant one of these indexes instead" in str(e) and "['Bhutan']" in str(e).replace("\\", "")

    async def test_dangerous_builtins_calls_are_blocked(self):
        unsafe_code = "import os"
        dangerous_code = f"""
exec = callable.__self__.exec
compile = callable.__self__.compile
exec(compile('{unsafe_code}', 'no filename', 'exec'))
"""

        with pytest.raises(InterpreterError):
            await evaluate_python_code(unsafe_code, static_tools=BASE_PYTHON_TOOLS)

        with pytest.raises(InterpreterError):
            await evaluate_python_code(dangerous_code, static_tools=BASE_PYTHON_TOOLS)

    async def test_dangerous_builtins_are_callable_if_explicitly_added(self):
        dangerous_code = """
compile = callable.__self__.compile
eval = callable.__self__.eval
exec = callable.__self__.exec

eval("1 + 1")
exec(compile("1 + 1", "no filename", "exec"))

teval("1 + 1")
texec(tcompile("1 + 1", "no filename", "exec"))
        """

        await evaluate_python_code(
            dangerous_code, static_tools={"tcompile": compile, "teval": eval, "texec": exec} | BASE_PYTHON_TOOLS
        )

    async def test_can_import_os_if_explicitly_authorized(self):
        dangerous_code = "import os; os.listdir('./')"
        await evaluate_python_code(dangerous_code, authorized_imports=["os"])

    async def test_can_import_os_if_all_imports_authorized(self):
        dangerous_code = "import os; os.listdir('./')"
        await evaluate_python_code(dangerous_code, authorized_imports=["*"])

    @pytest.mark.filterwarnings("ignore::DeprecationWarning")
    def test_can_import_scipy_if_explicitly_authorized(self):
        code = "import scipy"
        evaluate_python_code(code, authorized_imports=["scipy"])

    @pytest.mark.filterwarnings("ignore::DeprecationWarning")
    def test_can_import_sklearn_if_explicitly_authorized(self):
        code = "import sklearn"
        evaluate_python_code(code, authorized_imports=["sklearn"])

    def test_function_def_recovers_source_code(self):
        executor = LocalPythonExecutor([])

        executor.send_tools({"final_answer": FinalAnswerTool()})

        res, _, _ = executor(
            dedent(
                """
                def target_function():
                    return "Hello world"

                final_answer(target_function)
                """
            )
        )
        assert res.__name__ == "target_function"
        assert res.__source__ == "def target_function():\n    return 'Hello world'"

    def test_evaluate_class_def_with_pass(self):
        code = dedent("""
            class TestClass:
                pass

            instance = TestClass()
            instance.attr = "value"
            result = instance.attr
        """)
        state = {}
        result, _ = evaluate_python_code(code, BASE_PYTHON_TOOLS, state=state)
        assert result == "value"

    def test_evaluate_class_def_with_ann_assign_name(self):
        """
        Test evaluate_class_def function when stmt is an instance of ast.AnnAssign with ast.Name target.

        This test verifies that annotated assignments within a class definition are correctly evaluated.
        """
        code = dedent("""
            class TestClass:
                x: int = 5
                y: str = "test"

            instance = TestClass()
            result = (instance.x, instance.y)
        """)

        state = {}
        result, _ = evaluate_python_code(code, BASE_PYTHON_TOOLS, state=state)

        assert result == (5, "test")
        assert isinstance(state["TestClass"], type)
        # Values are wrapped by safer_func
        annotations = {key: value.__wrapped__ for key, value in state["TestClass"].__annotations__.items()}
        assert annotations == {"x": int, "y": str}
        assert state["TestClass"].x == 5
        assert state["TestClass"].y == "test"
        assert isinstance(state["instance"], state["TestClass"])
        assert state["instance"].x == 5
        assert state["instance"].y == "test"

    def test_evaluate_class_def_with_ann_assign_attribute(self):
        """
        Test evaluate_class_def function when stmt is an instance of ast.AnnAssign with ast.Attribute target.

        This test ensures that class attributes using attribute notation are correctly handled.
        """
        code = dedent("""
        class TestSubClass:
            attr = 1
        class TestClass:
            data: TestSubClass = TestSubClass()
            data.attr: str = "value"

        result = TestClass.data.attr
        """)

        state = {}
        result, _ = evaluate_python_code(code, BASE_PYTHON_TOOLS, state=state)

        assert result == "value"
        assert isinstance(state["TestClass"], type)
        assert state["TestClass"].__annotations__.keys() == {"data"}
        assert isinstance(state["TestClass"].__annotations__["data"], type)
        assert state["TestClass"].__annotations__["data"].__name__ == "TestSubClass"
        assert state["TestClass"].data.attr == "value"

    def test_evaluate_class_def_with_ann_assign_subscript(self):
        """
        Test evaluate_class_def function when stmt is an instance of ast.AnnAssign with ast.Subscript target.

        This test ensures that class attributes using subscript notation are correctly handled.
        """
        code = dedent("""
        class TestClass:
            key_data: dict = {}
            key_data["key"]: str = "value"
            index_data: list = [10, 20, 30]
            index_data[0:2]: list[str] = ["a", "b"]

        result = (TestClass.key_data['key'], TestClass.index_data[1:])
        """)

        state = {}
        result, _ = evaluate_python_code(code, BASE_PYTHON_TOOLS, state=state)

        assert result == ("value", ["b", 30])
        assert isinstance(state["TestClass"], type)
        # Values are wrapped by safer_func
        annotations = {key: value.__wrapped__ for key, value in state["TestClass"].__annotations__.items()}
        assert annotations == {"key_data": dict, "index_data": list}
        assert state["TestClass"].key_data == {"key": "value"}
        assert state["TestClass"].index_data == ["a", "b", 30]

    def test_evaluate_annassign(self):
        code = dedent("""\
            # Basic annotated assignment
            x: int = 42

            # Type annotations with expressions
            y: float = x / 2

            # Type annotation without assignment
            z: list

            # Type annotation with complex value
            names: list = ["Alice", "Bob", "Charlie"]

            # Type hint shouldn't restrict values at runtime
            s: str = 123  # Would be a type error in static checking, but valid at runtime

            # Access the values
            result = (x, y, names, s)
        """)
        state = {}
        evaluate_python_code(code, BASE_PYTHON_TOOLS, state=state)
        assert state["x"] == 42
        assert state["y"] == 21.0
        assert "z" not in state  # z should be not be defined
        assert state["names"] == ["Alice", "Bob", "Charlie"]
        assert state["s"] == 123  # Type hints don't restrict at runtime
        assert state["result"] == (42, 21.0, ["Alice", "Bob", "Charlie"], 123)

    @pytest.mark.parametrize(
        "code, expected_result",
        [
            (
                dedent("""\
                    x = 1
                    x += 2
                """),
                3,
            ),
            (
                dedent("""\
                    x = "a"
                    x += "b"
                """),
                "ab",
            ),
            (
                dedent("""\
                    class Custom:
                        def __init__(self, value):
                            self.value = value
                        def __iadd__(self, other):
                            self.value += other * 10
                            return self

                x = Custom(1)
                x += 2
                x.value
            """),
            21,
        ),
    ],
)
async def test_evaluate_augassign(code, expected_result):
    state = {}
    result, _ = await evaluate_python_code(code, {}, state=state)
    assert result == expected_result


@pytest.mark.parametrize(
    "operator, expected_result",
    [
        ("+=", 7),
        ("-=", 3),
        ("*=", 10),
        ("/=", 2.5),
        ("//=", 2),
        ("%=", 1),
        ("**=", 25),
        ("&=", 0),
        ("|=", 7),
        ("^=", 7),
        (">>=", 1),
        ("<<=", 20),
    ],
)
async def test_evaluate_augassign_number(operator, expected_result):
    code = dedent("""\
        x = 5
        x {operator} 2
    """).format(operator=operator)
    state = {}
    result, _ = await evaluate_python_code(code, {}, state=state)
    assert result == expected_result


@pytest.mark.parametrize(
    "operator, expected_result",
    [
        ("+=", 7),
        ("-=", 3),
        ("*=", 10),
        ("/=", 2.5),
        ("//=", 2),
        ("%=", 1),
        ("**=", 25),
        ("&=", 0),
        ("|=", 7),
        ("^=", 7),
        (">>=", 1),
        ("<<=", 20),
    ],
)
async def test_evaluate_augassign_custom(operator, expected_result):
    operator_names = {
        "+=": "iadd",
        "-=": "isub",
        "*=": "imul",
        "/=": "itruediv",
        "//=": "ifloordiv",
        "%=": "imod",
        "**=": "ipow",
        "&=": "iand",
        "|=": "ior",
        "^=": "ixor",
        ">>=": "irshift",
        "<<=": "ilshift",
    }
    code = dedent("""\
        class Custom:
            def __init__(self, value):
                self.value = value
            def __{operator_name}__(self, other):
                self.value {operator} other
                return self

        x = Custom(5)
        x {operator} 2
        x.value
    """).format(operator=operator, operator_name=operator_names[operator])
    state = {}
    result, _ = await evaluate_python_code(code, {}, state=state)
    assert result == expected_result


@pytest.mark.parametrize(
    "code, expected_error_message",
    [
        (
            dedent("""\
                x = 5
                del x
                x
            """),
            "The variable `x` is not defined",
        ),
        (
            dedent("""\
                x = [1, 2, 3]
                del x[2]
                x[2]
            """),
            "Index 2 out of bounds for list of length 2",
        ),
        (
            dedent("""\
                x = {"key": "value"}
                del x["key"]
                x["key"]
            """),
            "Could not index {} with 'key'",
        ),
        (
            dedent("""\
                del x
            """),
            "Cannot delete name 'x': name is not defined",
        ),
    ],
)
async def test_await evaluate_python_code_with_evaluate_delete(code, expected_error_message):
    state = {}
    with pytest.raises(InterpreterError) as exception_info:
        await evaluate_python_code(code, {}, state=state)
    assert expected_error_message in str(exception_info.value)


@pytest.mark.parametrize(
    "code, state, expectation",
    [
        ("del x", {"x": 1}, {}),
        ("del x[1]", {"x": [1, 2, 3]}, {"x": [1, 3]}),
        ("del x['key']", {"x": {"key": "value"}}, {"x": {}}),
        ("del x", {}, InterpreterError("Cannot delete name 'x': name is not defined")),
    ],
)
async def test_evaluate_delete(code, state, expectation):
    delete_node = ast.parse(code).body[0]
    if isinstance(expectation, Exception):
        with pytest.raises(type(expectation)) as exception_info:
            evaluate_delete(delete_node, state, {}, {}, [])
        assert str(expectation) in str(exception_info.value)
    else:
        evaluate_delete(delete_node, state, {}, {}, [])
        _ = state.pop("_operations_count", None)
        assert state == expectation


@pytest.mark.parametrize(
    "condition, state, expected_result",
    [
        ("a == b", {"a": 1, "b": 1}, True),
        ("a == b", {"a": 1, "b": 2}, False),
        ("a != b", {"a": 1, "b": 1}, False),
        ("a != b", {"a": 1, "b": 2}, True),
        ("a < b", {"a": 1, "b": 1}, False),
        ("a < b", {"a": 1, "b": 2}, True),
        ("a < b", {"a": 2, "b": 1}, False),
        ("a <= b", {"a": 1, "b": 1}, True),
        ("a <= b", {"a": 1, "b": 2}, True),
        ("a <= b", {"a": 2, "b": 1}, False),
        ("a > b", {"a": 1, "b": 1}, False),
        ("a > b", {"a": 1, "b": 2}, False),
        ("a > b", {"a": 2, "b": 1}, True),
        ("a >= b", {"a": 1, "b": 1}, True),
        ("a >= b", {"a": 1, "b": 2}, False),
        ("a >= b", {"a": 2, "b": 1}, True),
        ("a is b", {"a": 1, "b": 1}, True),
        ("a is b", {"a": 1, "b": 2}, False),
        ("a is not b", {"a": 1, "b": 1}, False),
        ("a is not b", {"a": 1, "b": 2}, True),
        ("a in b", {"a": 1, "b": [1, 2, 3]}, True),
        ("a in b", {"a": 4, "b": [1, 2, 3]}, False),
        ("a not in b", {"a": 1, "b": [1, 2, 3]}, False),
        ("a not in b", {"a": 4, "b": [1, 2, 3]}, True),
        # Composite conditions:
        ("a == b == c", {"a": 1, "b": 1, "c": 1}, True),
        ("a == b == c", {"a": 1, "b": 2, "c": 1}, False),
        ("a == b < c", {"a": 1, "b": 1, "c": 1}, False),
        ("a == b < c", {"a": 1, "b": 1, "c": 2}, True),
    ],
)
async def test_evaluate_condition(condition, state, expected_result):
    condition_ast = ast.parse(condition, mode="eval").body
    result = evaluate_condition(condition_ast, state, {}, {}, [])
    assert result == expected_result


async def test_get_safe_module_handle_lazy_imports():
    class FakeModule(types.ModuleType):
        def __init__(self, name):
            super().__init__(name)
            self.non_lazy_attribute = "ok"

        def __getattr__(self, name):
            if name == "lazy_attribute":
                raise ImportError("lazy import failure")
            return super().__getattr__(name)

        def __dir__(self):
            return super().__dir__() + ["lazy_attribute"]

    fake_module = FakeModule("fake_module")
    safe_module = get_safe_module(fake_module, authorized_imports=set())
    assert not hasattr(safe_module, "lazy_attribute")
    assert getattr(safe_module, "non_lazy_attribute") == "ok"


async def test_non_standard_comparisons():
    code = """
class NonStdEqualsResult:
    def __init__(self, left:object, right:object):
        self._left = left
        self._right = right
    def __str__(self) -> str:
        return f'{self._left}=={self._right}'

class NonStdComparisonClass:
    def __init__(self, value: str ):
        self._value = value
    def __str__(self):
        return self._value
    def __eq__(self, other):
        return NonStdEqualsResult(self, other)
a = NonStdComparisonClass("a")
b = NonStdComparisonClass("b")
result = a == b
    """
    result, _ = await evaluate_python_code(code, state={})
    assert not isinstance(result, bool)
    assert str(result) == "a==b"


class TestPrintContainer:
    async def test_initial_value(self):
        pc = PrintContainer()
        assert pc.value == ""

    async def test_append(self):
        pc = PrintContainer()
        pc.append("Hello")
        assert pc.value == "Hello"

    async def test_iadd(self):
        pc = PrintContainer()
        pc += "World"
        assert pc.value == "World"

    async def test_str(self):
        pc = PrintContainer()
        pc.append("Hello")
        assert str(pc) == "Hello"

    async def test_repr(self):
        pc = PrintContainer()
        pc.append("Hello")
        assert repr(pc) == "PrintContainer(Hello)"

    async def test_len(self):
        pc = PrintContainer()
        pc.append("Hello")
        assert len(pc) == 5


def test_fix_final_answer_code():
    test_cases = [
        (
            "final_answer = 3.21\nfinal_answer(final_answer)",
            "final_answer_variable = 3.21\nfinal_answer(final_answer_variable)",
        ),
        (
            "x = final_answer(5)\nfinal_answer = x + 1\nfinal_answer(final_answer)",
            "x = final_answer(5)\nfinal_answer_variable = x + 1\nfinal_answer(final_answer_variable)",
        ),
        (
            "def func():\n    final_answer = 42\n    return final_answer(final_answer)",
            "def func():\n    final_answer_variable = 42\n    return final_answer(final_answer_variable)",
        ),
        (
            "final_answer(5)  # Should not change function calls",
            "final_answer(5)  # Should not change function calls",
        ),
        (
            "obj.final_answer = 5  # Should not change object attributes",
            "obj.final_answer = 5  # Should not change object attributes",
        ),
        (
            "final_answer=3.21;final_answer(final_answer)",
            "final_answer_variable=3.21;final_answer(final_answer_variable)",
        ),
    ]

    for i, (input_code, expected) in enumerate(test_cases, 1):
        result = fix_final_answer_code(input_code)
        assert result == expected, f"""
Test case {i} failed:
Input:    {input_code}
Expected: {expected}
Got:      {result}
"""


@pytest.mark.parametrize(
    "module,authorized_imports,expected",
    [
        ("os", ["other", "*"], True),
        ("AnyModule", ["*"], True),
        ("os", ["os"], True),
        ("AnyModule", ["AnyModule"], True),
        ("Module.os", ["Module"], False),
        ("Module.os", ["Module", "os"], True),
        ("os.path", ["os"], True),
        ("os", ["os.path"], False),
    ],
)
async def test_check_module_authorized(module: str, authorized_imports: list[str], expected: bool):
    dangerous_patterns = (
        "_os",
        "os",
        "subprocess",
        "_subprocess",
        "pty",
        "system",
        "popen",
        "spawn",
        "shutil",
        "sys",
        "pathlib",
        "io",
        "socket",
        "compile",
        "eval",
        "exec",
        "multiprocessing",
    )
    assert check_module_authorized(module, authorized_imports, dangerous_patterns) == expected
