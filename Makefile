PY ?= python3

.PHONY: test api run build build-offline docker-run docker-test docker-smoke golden golden-update conform bench

test:
	$(PY) tools/task.py test

api:
	$(PY) tools/task.py api

run:
	$(PY) tools/task.py run $(IN) $(OUT)

build:
	$(PY) tools/task.py build

build-offline:
	$(PY) tools/task.py build-offline

docker-run:
	$(PY) tools/task.py docker-run $(IN) $(OUT)

docker-test:
	$(PY) tools/task.py docker-test

docker-smoke:
	$(PY) tools/task.py docker-smoke

# make golden [FORMAT=stub]
golden:
	$(PY) tools/task.py golden $(FORMAT)

# make golden-update FORMAT=stub
golden-update:
	$(PY) tools/task.py golden-update $(FORMAT)

# make conform [NAME=stub] [ARGS=--verbose]
conform:
	$(PY) tools/task.py conform $(NAME) $(ARGS)

# make bench [ARGS=--docker]
bench:
	$(PY) tools/task.py bench $(ARGS)
