#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import argparse
from typing import Any, Dict, List, Tuple

import lark
from xml.etree import ElementTree as ET

# ---------- Грамматика Lark ----------

grammar = r"""
start: statement*

statement: const_decl

const_decl: NAME ":" value ";"

?value: number
      | dictionary
      | expr

number: NUMBER

dictionary: "begin" dict_entry* "end"

dict_entry: NAME ":=" value ";"

expr: "$" expr_item+ "$"

?expr_item: NUMBER      -> expr_number
          | NAME        -> expr_name
          | "+"         -> expr_plus
          | "-"         -> expr_minus
          | "*"         -> expr_mul
          | "/"         -> expr_div

NAME: /[a-z][a-z0-9_]*/
NUMBER: /[0-9]+(\.[0-9]+)?/

COMMENT: /\|\|[^\n]*/
MLCOMMENT: "=begin" /(.|\n)*?/ "=cut"

%ignore COMMENT
%ignore MLCOMMENT
%ignore /[ \t\r\n]+/
"""


class BuildAST(lark.Transformer):
    def statement(self, items):
        return items[0]

    def start(self, items):
        return items

    def const_decl(self, items):
        name_token, value = items
        return (str(name_token), value)

    def number(self, items):
        (token,) = items
        return float(token)

    def dictionary(self, items):
        d: Dict[str, Any] = {}
        for key, value in items:
            if key in d:
                raise ValueError(f"Duplicate key in dictionary: {key}")
            d[key] = value
        return ("dict", d)

    def dict_entry(self, items):
        name_token, value = items
        return (str(name_token), value)

    def expr(self, items):
        return ("expr", items)

    def expr_number(self, items):
        (token,) = items
        return float(token)

    def expr_name(self, items):
        (token,) = items
        return str(token)

    def expr_plus(self, _):
        return "+"

    def expr_minus(self, _):
        return "-"

    def expr_mul(self, _):
        return "*"

    def expr_div(self, _):
        return "/"


def eval_config(ast: List[Tuple[str, Any]]) -> Dict[str, Any]:
    env: Dict[str, Any] = {}
    result: Dict[str, Any] = {}

    def eval_value(node: Any) -> Any:
        if isinstance(node, (int, float)):
            return float(node)

        if isinstance(node, tuple) and node and node[0] == "dict":
            d: Dict[str, Any] = {}
            for k, v_ast in node[1].items():
                d[k] = eval_value(v_ast)
            return d

        if isinstance(node, tuple) and node and node[0] == "expr":
            return eval_expr(node[1])

        raise ValueError(f"Invalid value node: {node!r}")

    def eval_expr(tokens: List[Any]) -> float:
        stack: List[float] = []

        for tok in tokens:
            if isinstance(tok, (int, float)):
                stack.append(float(tok))
                continue

            if isinstance(tok, str):
                if tok in {"+", "-", "*", "/", "min"}:
                    if tok == "min":
                        if len(stack) < 2:
                            raise ValueError("min requires at least two operands")
                        b = stack.pop()
                        a = stack.pop()
                        stack.append(min(a, b))
                    else:
                        if len(stack) < 2:
                            raise ValueError(f"Operator {tok} requires two operands")
                        b = stack.pop()
                        a = stack.pop()
                        if tok == "+":
                            stack.append(a + b)
                        elif tok == "-":
                            stack.append(a - b)
                        elif tok == "*":
                            stack.append(a * b)
                        elif tok == "/":
                            stack.append(a / b)
                    continue

                if tok not in env:
                    raise ValueError(f"Unknown constant in expression: {tok}")
                val = env[tok]
                if not isinstance(val, (int, float)):
                    raise ValueError(f"Constant {tok} is not numeric")
                stack.append(float(val))
                continue

            raise ValueError(f"Invalid token in expression: {tok!r}")

        if len(stack) != 1:
            raise ValueError("Expression did not reduce to a single value")
        return stack[0]

    for name, val_ast in ast:
        value = eval_value(val_ast)
        env[name] = value
        result[name] = value

    return result


def build_xml(data: Dict[str, Any]) -> ET.Element:
    root = ET.Element("config")

    def add_value(parent: ET.Element, name: str, value: Any):
        if isinstance(value, dict):
            elem = ET.SubElement(parent, "dict", name=name)
            for k, v in value.items():
                add_value(elem, k, v)
        else:
            elem = ET.SubElement(parent, "number", name=name)
            elem.text = str(value)

    for name, val in data.items():
        add_value(root, name, val)

    return root


parser = lark.Lark(grammar, parser="lalr")


def main(argv: List[str] | None = None) -> None:
    argp = argparse.ArgumentParser(
        description="Транслятор учебного конфигурационного языка в XML"
    )
    argp.add_argument(
        "-i",
        "--input",
        help="Путь к входному файлу (если не указан, читаем из stdin)",
    )
    argp.add_argument(
        "-o",
        "--output",
        required=True,
        help="Путь к выходному XML-файлу",
    )
    args = argp.parse_args(argv)

    # Читаем исходный текст
    if args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    try:
        tree = parser.parse(text)
    except lark.LarkError as e:
        print(f"Syntax error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        ast = BuildAST().transform(tree)
        data = eval_config(ast)
    except Exception as e:
        print(f"Semantic error: {e}", file=sys.stderr)
        sys.exit(1)

    root = build_xml(data)
    et = ET.ElementTree(root)
    et.write(args.output, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    main()
