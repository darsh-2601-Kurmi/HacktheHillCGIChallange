# On Windows without make, use: python run.py <target>
PY ?= python

.PHONY: run data test valuecase reset
run:
	$(PY) run.py run
data:
	$(PY) run.py data
test:
	$(PY) run.py test
valuecase:
	$(PY) run.py valuecase
reset:
	$(PY) run.py reset
