# ---------- ---------- ---------- ---------- ---------- ----------
#
# chat_bot
#
#    1) config, vars, and target
#    2) functions
#    3) phonies
#
# ---------- ---------- ---------- ---------- ---------- ----------

NAME=chat_bot

target: help


# ---------- ---------- ---------- ---------- ---------- ----------
# functions
# ---------- ---------- ---------- ---------- ---------- ----------

define fix-python
	@isort . || echo "isort returned nonzero"
	@black --check . || echo "black returned nonzero"
endef


define lint
	@flake8 . || echo "flake8 returned nonzero"
endef


define lint-types
	@mypy . || echo "mypy returned nonzero"
endef


# define run-safety
# 	@safety check || echo "safety returned nonzero"
# endef


# ---------- ---------- ---------- ---------- ---------- ----------
# phonies
# ---------- ---------- ---------- ---------- ---------- ----------

.PHONY: help
help:
	@echo "Usage: make [PHONY]"
	@sed -n -e "/sed/! s/\.PHONY: //p" Makefile


.PHONY: clean
clean:
	@py3clean . || echo "executing py3clean returned nonzero"

.PHONY: fix-python
fix-python:
	@$(call fix-python)


.PHONY: fix-all
fix-all: fix-python


.PHONY: lint
lint:
	@$(call lint)


.PHONY: lint-types
lint-types:
	@$(call lint-types)


.PHONY: run-safety
run-safety:
	# @$(call run-safety)


.PHONY: dev
dev: fix-all lint lint-types show-lacking-coverage


.PHONY: test-coverage
test-coverage:
	@coverage run -m unittest discover -s tests -t .


.PHONY: test-coverage-report
test-coverage-report: test-coverage
	@coverage report -m


.PHONY: show-lacking-coverage
show-lacking-coverage: test-coverage
	@coverage report -m | grep -v '100\%'


.PHONY: test
test:
	@python3 -m unittest discover -s tests -t . ||\
            echo "unit tests failed"
