PY ?= python3

.PHONY: test api run build build-offline docker-run docker-test docker-smoke golden golden-update

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
