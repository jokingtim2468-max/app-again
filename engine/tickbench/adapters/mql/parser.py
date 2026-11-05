"""MQL4 / MQL5 lexer and parser (the C-like subset Expert Advisors use)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ...errors import ScriptError, UnsupportedFeature

TYPES = {"void", "int", "uint", "long", "ulong", "short", "ushort", "char", "uchar", "bool", "double", "float",
         "string", "datetime", "color", "MqlTick", "MqlRates", "MqlDateTime", "MqlTradeRequest",
         "MqlTradeResult", "MqlTradeCheckResult", "MqlBookInfo", "CTrade", "CPositionInfo", "CSymbolInfo",
         "COrderInfo", "CAccountInfo", "CDealInfo", "CHistoryOrderInfo"}
INT_TYPES = {"int", "uint", "long", "ulong", "short", "ushort", "char", "uchar", "datetime", "color"}
MODIFIERS = {"static", "const", "input", "extern", "sinput", "export", "virtual", "public", "private", "protected"}

TOKEN_RE = re.compile(r"""
    (?P<ws>\s+)
  | (?P<comment>//[^\n]*|/\*.*?\*/)
  | (?P<dt>D'[^']*')
  | (?P<clr>C'[^']*')
  | (?P<num>0[xX][0-9A-Fa-f]+|(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?)
  | (?P<str>"(?:[^"\\\n]|\\.)*")
  | (?P<chr>'(?:[^'\\]|\\.)')
  | (?P<op><<=|>>=|\+\+|--|\+=|-=|\*=|/=|%=|&=|\|=|\^=|<<|>>|==|!=|<=|>=|&&|\|\||->|::|[-+*/%<>=!~&|^?:;,.(){}\[\]])
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
""", re.X | re.S)


@dataclass
class Tok:
    kind: str
    value: Any
    line: int
    comment: str = ""   # trailing // comment on the same line (input titles)


@dataclass
class Node:
    kind: str
    line: int
    a: Any = None
    b: Any = None
    c: Any = None
    d: Any = None
    kids: list = field(default_factory=list)


def preprocess(src: str) -> tuple[str, dict, dict]:
    """Handle #define (object-like), #property, #include; returns (source, defines, properties)."""
    defines: dict[str, str] = {}
    props: dict[str, str] = {}
    out = []
    for line in src.replace("\r\n", "\n").split("\n"):
        s = line.strip()
        if s.startswith("#"):
            m = re.match(r"#\s*define\s+([A-Za-z_]\w*)(\([^)]*\))?\s*(.*)$", s)
            if m:
                if m.group(2):
                    raise UnsupportedFeature(f"Function-like macro #define {m.group(1)}{m.group(2)} isn't supported.",
                                             hint="Turn it into a normal function.")
                val = re.sub(r"//.*$", "", m.group(3)).strip()
                defines[m.group(1)] = val
            m = re.match(r"#\s*property\s+(\w+)\s*(.*)$", s)
            if m:
                props[m.group(1)] = m.group(2).strip().strip('"')
            out.append("")  # keep line numbers
            continue
        out.append(line)
    return "\n".join(out), defines, props


def tokenize(src: str, defines: dict) -> list[Tok]:
    toks: list[Tok] = []
    pos = 0
    line = 1
    n = len(src)
    while pos < n:
        m = TOKEN_RE.match(src, pos)
        if not m:
            raise ScriptError(f"Unexpected character '{src[pos]}'", line=line)
        kind = m.lastgroup
        text = m.group(kind)
        if kind == "comment":
            if text.startswith("//") and toks and toks[-1].line == line:
                # trailing comment on a declaration line: used as an input's display name
                toks[-1].comment = text[2:].strip()
        elif kind == "num":
            v = int(text, 16) if text.lower().startswith("0x") else (float(text) if re.search(r"[.eE]", text) else int(text))
            toks.append(Tok("num", v, line))
        elif kind == "str":
            body = text[1:-1]
            body = body.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"').replace("\\\\", "\\")
            toks.append(Tok("str", body, line))
        elif kind == "chr":
            body = text[1:-1]
            toks.append(Tok("num", ord(body.encode().decode("unicode_escape")), line))
        elif kind == "dt":
            toks.append(Tok("dt", text[2:-1], line))
        elif kind == "clr":
            toks.append(Tok("num", 0, line))
        elif kind == "op":
            toks.append(Tok("op", text, line))
        elif kind == "name":
            if text in defines and defines[text] != "":
                sub = tokenize(defines[text], {k: v for k, v in defines.items() if k != text})
                for t in sub:
                    t.line = line
                toks.extend(sub)
            else:
                toks.append(Tok("name", text, line))
        line += text.count("\n")
        pos = m.end()
    toks.append(Tok("EOF", None, line))
    return toks


BINARY_PREC = [
    ("||",), ("&&",), ("|",), ("^",), ("&",), ("==", "!="), ("<", ">", "<=", ">="), ("<<", ">>"), ("+", "-"),
    ("*", "/", "%"),
]
ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="}


class Parser:
    def __init__(self, src: str):
        clean, self.defines, self.properties = preprocess(src)
        self.toks = tokenize(clean, self.defines)
        self.p = 0
        self.enums: dict[str, dict[str, int]] = {}
        self.type_names = set(TYPES)

    @property
    def t(self) -> Tok:
        return self.toks[self.p]

    def peek(self, k=1) -> Tok:
        return self.toks[min(self.p + k, len(self.toks) - 1)]

    def at_op(self, *v) -> bool:
        return self.t.kind == "op" and self.t.value in v

    def at_name(self, *v) -> bool:
        return self.t.kind == "name" and self.t.value in v

    def eat_op(self, v) -> Tok:
        if not self.at_op(v):
            raise ScriptError(f"Expected '{v}' but found '{self.t.value}'", line=self.t.line)
        t = self.t
        self.p += 1
        return t

    def eat_name(self) -> str:
        if self.t.kind != "name":
            raise ScriptError(f"Expected a name but found '{self.t.value}'", line=self.t.line)
        v = self.t.value
        self.p += 1
        return v

    def is_type(self, tok: Tok | None = None) -> bool:
        tok = tok or self.t
        return tok.kind == "name" and (tok.value in self.type_names or tok.value.startswith("ENUM_"))

    # ------------------------------------------------------------------ top level
    def parse(self) -> list[Node]:
        out = []
        while self.t.kind != "EOF":
            if self.at_op(";"):
                self.p += 1
                continue
            out.extend(self.top_item())
        return out

    def top_item(self) -> list[Node]:
        line = self.t.line
        if self.at_name("enum"):
            self.enum_decl()
            return []
        if self.at_name("struct", "class", "interface", "union", "template", "namespace"):
            # Allow forward declarations, reject bodies
            if self.peek(2).kind == "op" and self.peek(2).value == ";":
                self.p += 3
                return []
            raise UnsupportedFeature(f"'{self.t.value}' definitions aren't supported.", line=line,
                                     hint="Keep EA logic in plain functions; built-in CTrade/MqlTick are fine.")
        if self.at_name("import"):
            raise UnsupportedFeature("#import / DLL calls aren't supported.", line=line)
        mods = []
        while self.t.kind == "name" and self.t.value in MODIFIERS:
            mods.append(self.t.value)
            self.p += 1
        if not self.is_type() and not (self.t.kind == "name" and self.peek().kind == "name"):
            raise ScriptError(f"Unexpected '{self.t.value}' at top level.", line=line,
                              hint="Expected a declaration or a function.")
        typ = self.eat_name()
        while self.at_op("&") or self.at_op("*"):
            self.p += 1
        name = self.eat_name()
        if self.at_op("("):
            return [self.func_def(typ, name, line)]
        decls = self.var_decl_rest(typ, name, line, mods)
        self.eat_op(";")
        return decls

    def enum_decl(self):
        self.p += 1
        ename = self.eat_name()
        self.type_names.add(ename)
        self.eat_op("{")
        vals: dict[str, int] = {}
        nxt = 0
        while not self.at_op("}"):
            n = self.eat_name()
            if self.at_op("="):
                self.p += 1
                neg = False
                if self.at_op("-"):
                    neg = True
                    self.p += 1
                tk = self.t
                self.p += 1
                if tk.kind == "num":
                    nxt = -int(tk.value) if neg else int(tk.value)
                elif tk.kind == "name":
                    nxt = vals.get(tk.value, 0)
            vals[n] = nxt
            nxt += 1
            if self.at_op(","):
                self.p += 1
        self.eat_op("}")
        if self.at_op(";"):
            self.p += 1
        self.enums[ename] = vals

    def func_def(self, typ, name, line) -> Node:
        self.eat_op("(")
        params = []
        while not self.at_op(")"):
            while self.at_name("const"):
                self.p += 1
            ptype = self.eat_name()
            byref = False
            while self.at_op("&", "*"):
                byref = True
                self.p += 1
            pname = self.eat_name()
            is_arr = False
            while self.at_op("["):
                self.p += 1
                while not self.at_op("]"):
                    self.p += 1
                self.p += 1
                is_arr = True
            default = None
            if self.at_op("="):
                self.p += 1
                default = self.expr()
            params.append({"type": ptype, "name": pname, "ref": byref, "array": is_arr, "default": default})
            if self.at_op(","):
                self.p += 1
        self.eat_op(")")
        while self.at_name("const"):
            self.p += 1
        if self.at_op(";"):
            self.p += 1
            return Node("proto", line, a=name)
        body = self.block()
        return Node("func", line, a=name, b=params, c=body, d=typ)

    def var_decl_rest(self, typ, name, line, mods) -> list[Node]:
        out = []
        while True:
            dims = []
            while self.at_op("["):
                self.p += 1
                dims.append(None if self.at_op("]") else self.expr())
                self.eat_op("]")
            init = None
            comment = self.toks[self.p - 1].comment
            if self.at_op("="):
                self.p += 1
                if self.at_op("{"):
                    init = self.init_list()
                else:
                    init = self.expr()
                comment = self.toks[self.p - 1].comment or comment
            elif self.at_op("("):  # constructor-style init: CTrade trade(); or int x(5)
                self.p += 1
                args = []
                while not self.at_op(")"):
                    args.append(self.expr())
                    if self.at_op(","):
                        self.p += 1
                self.eat_op(")")
                init = args[0] if args else None
            out.append(Node("var", line, a=name, b=typ, c=init, d={"mods": mods, "dims": dims,
                                                                     "comment": comment}))
            if self.at_op(","):
                self.p += 1
                while self.at_op("&", "*"):
                    self.p += 1
                name = self.eat_name()
                continue
            break
        # trailing comment might be attached to ';'
        if self.at_op(";") and self.t.comment:
            for d in out:
                if not d.d["comment"]:
                    d.d["comment"] = self.t.comment
        return out

    def init_list(self) -> Node:
        line = self.t.line
        self.eat_op("{")
        items = []
        while not self.at_op("}"):
            items.append(self.init_list() if self.at_op("{") else self.expr())
            if self.at_op(","):
                self.p += 1
        self.eat_op("}")
        return Node("initlist", line, a=items)

    # ------------------------------------------------------------------ statements
    def block(self) -> Node:
        line = self.t.line
        self.eat_op("{")
        stmts = []
        while not self.at_op("}"):
            if self.t.kind == "EOF":
                raise ScriptError("Missing '}' — a block was never closed.", line=line)
            s = self.statement()
            if s is not None:
                stmts.append(s)
        self.eat_op("}")
        return Node("block", line, a=stmts)

    def statement(self) -> Node | None:
        t = self.t
        line = t.line
        if self.at_op(";"):
            self.p += 1
            return None
        if self.at_op("{"):
            return self.block()
        if t.kind == "name":
            v = t.value
            if v == "if":
                self.p += 1
                self.eat_op("(")
                cond = self.expr()
                self.eat_op(")")
                then = self.statement()
                other = None
                if self.at_name("else"):
                    self.p += 1
                    other = self.statement()
                return Node("if", line, a=cond, b=then, c=other)
            if v == "for":
                self.p += 1
                self.eat_op("(")
                init = None
                if not self.at_op(";"):
                    if self.is_decl_start():
                        init = self.local_decl()
                    else:
                        init = Node("exprs", line, a=self.expr_list())
                self.eat_op(";")
                cond = None if self.at_op(";") else self.expr()
                self.eat_op(";")
                step = None if self.at_op(")") else Node("exprs", line, a=self.expr_list())
                self.eat_op(")")
                body = self.statement()
                return Node("for", line, a=init, b=cond, c=step, d=body)
            if v == "while":
                self.p += 1
                self.eat_op("(")
                cond = self.expr()
                self.eat_op(")")
                return Node("while", line, a=cond, b=self.statement())
            if v == "do":
                self.p += 1
                body = self.statement()
                if not self.at_name("while"):
                    raise ScriptError("Expected 'while' after do-block.", line=self.t.line)
                self.p += 1
                self.eat_op("(")
                cond = self.expr()
                self.eat_op(")")
                self.eat_op(";")
                return Node("dowhile", line, a=cond, b=body)
            if v == "switch":
                return self.switch()
            if v == "return":
                self.p += 1
                val = None if self.at_op(";") else self.expr()
                self.eat_op(";")
                return Node("return", line, a=val)
            if v == "break":
                self.p += 1
                self.eat_op(";")
                return Node("break", line)
            if v == "continue":
                self.p += 1
                self.eat_op(";")
                return Node("continue", line)
            if self.is_decl_start():
                d = self.local_decl()
                self.eat_op(";")
                return d
        e = self.expr()
        self.eat_op(";")
        return Node("expr", line, a=e)

    def is_decl_start(self) -> bool:
        k = self.p
        while self.toks[k].kind == "name" and self.toks[k].value in ("static", "const"):
            k += 1
        tk = self.toks[k]
        if tk.kind != "name":
            return False
        nx = self.toks[k + 1]
        while nx.kind == "op" and nx.value in ("&", "*"):
            k += 1
            nx = self.toks[k + 1]
        if self.is_type(tk):
            return nx.kind == "name"
        # unknown type name followed by a name: user type / class instance
        return nx.kind == "name" and tk.value not in ("return", "else", "case", "delete", "new")

    def local_decl(self) -> Node:
        line = self.t.line
        mods = []
        while self.at_name("static", "const"):
            mods.append(self.t.value)
            self.p += 1
        typ = self.eat_name()
        while self.at_op("&", "*"):
            self.p += 1
        name = self.eat_name()
        decls = self.var_decl_rest(typ, name, line, mods)
        return Node("decls", line, a=decls)

    def switch(self) -> Node:
        line = self.t.line
        self.p += 1
        self.eat_op("(")
        subj = self.expr()
        self.eat_op(")")
        self.eat_op("{")
        cases = []  # (value_expr or None for default, [stmts])
        while not self.at_op("}"):
            if self.at_name("case"):
                self.p += 1
                val = self.expr()
                self.eat_op(":")
                cases.append([val, []])
            elif self.at_name("default"):
                self.p += 1
                self.eat_op(":")
                cases.append([None, []])
            else:
                if not cases:
                    raise ScriptError("Statement before the first 'case' in switch.", line=self.t.line)
                s = self.statement()
                if s is not None:
                    cases[-1][1].append(s)
        self.eat_op("}")
        return Node("switch", line, a=subj, b=cases)

    # ------------------------------------------------------------------ expressions
    def expr_list(self) -> list[Node]:
        items = [self.expr()]
        while self.at_op(","):
            self.p += 1
            items.append(self.expr())
        return items

    def expr(self) -> Node:
        return self.assignment()

    def assignment(self) -> Node:
        left = self.ternary()
        if self.t.kind == "op" and self.t.value in ASSIGN_OPS:
            op = self.t.value
            line = self.t.line
            self.p += 1
            right = self.assignment()
            return Node("assign", line, a=op, b=left, c=right)
        return left

    def ternary(self) -> Node:
        cond = self.binary(0)
        if self.at_op("?"):
            line = self.t.line
            self.p += 1
            a = self.assignment()
            self.eat_op(":")
            b = self.assignment()
            return Node("ternary", line, a=cond, b=a, c=b)
        return cond

    def binary(self, level: int) -> Node:
        if level >= len(BINARY_PREC):
            return self.unary()
        left = self.binary(level + 1)
        ops = BINARY_PREC[level]
        while self.t.kind == "op" and self.t.value in ops:
            op = self.t.value
            line = self.t.line
            self.p += 1
            right = self.binary(level + 1)
            left = Node("bin", line, a=op, b=left, c=right)
        return left

    def unary(self) -> Node:
        t = self.t
        line = t.line
        if t.kind == "op":
            if t.value in ("!", "-", "+", "~"):
                self.p += 1
                return Node("unary", line, a=t.value, b=self.unary())
            if t.value in ("++", "--"):
                self.p += 1
                return Node("preinc", line, a=t.value, b=self.unary())
            if t.value == "(" and self.is_type(self.peek()) and self.peek(2).kind == "op" and self.peek(2).value == ")":
                self.p += 1
                typ = self.eat_name()
                self.eat_op(")")
                return Node("cast", line, a=typ, b=self.unary())
        return self.postfix()

    def postfix(self) -> Node:
        e = self.primary()
        while True:
            t = self.t
            if t.kind == "op" and t.value == "(":
                self.p += 1
                args = []
                while not self.at_op(")"):
                    args.append(self.assignment())
                    if self.at_op(","):
                        self.p += 1
                self.eat_op(")")
                e = Node("call", t.line, a=e, b=args)
            elif t.kind == "op" and t.value == "[":
                self.p += 1
                idx = self.expr()
                self.eat_op("]")
                e = Node("index", t.line, a=e, b=idx)
            elif t.kind == "op" and t.value in (".", "->"):
                self.p += 1
                e = Node("member", t.line, a=e, b=self.eat_name())
            elif t.kind == "op" and t.value == "::":
                self.p += 1
                e = Node("name", t.line, a=self.eat_name())
            elif t.kind == "op" and t.value in ("++", "--"):
                self.p += 1
                e = Node("postinc", t.line, a=t.value, b=e)
            else:
                break
        return e

    def primary(self) -> Node:
        t = self.t
        line = t.line
        if t.kind == "num":
            self.p += 1
            return Node("num", line, a=t.value)
        if t.kind == "str":
            self.p += 1
            s = t.value
            while self.t.kind == "str":  # adjacent literals concatenate
                s += self.t.value
                self.p += 1
            return Node("str", line, a=s)
        if t.kind == "dt":
            self.p += 1
            return Node("dt", line, a=t.value)
        if t.kind == "name":
            self.p += 1
            if t.value in ("true", "false"):
                return Node("num", line, a=t.value == "true")
            if t.value == "NULL":
                return Node("null", line)
            if t.value in self.type_names and self.at_op("("):  # function-style cast double(x)
                self.p += 1
                inner = self.expr()
                self.eat_op(")")
                return Node("cast", line, a=t.value, b=inner)
            return Node("name", line, a=t.value)
        if t.kind == "op" and t.value == "(":
            self.p += 1
            e = self.expr()
            while self.at_op(","):  # comma operator
                self.p += 1
                e = self.expr()
            self.eat_op(")")
            return e
        if t.kind == "op" and t.value == "::":
            self.p += 1
            return Node("name", line, a=self.eat_name())
        raise ScriptError(f"Unexpected '{t.value if t.value is not None else 'end of file'}'", line=line)


def parse(src: str) -> Parser:
    p = Parser(src)
    p.program = p.parse()
    return p
