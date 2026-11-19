"""Cascade step 3: a local decision model for the works the fusion model is unsure about.

A decision model here does not generate text. It is shown a prompt with a fixed set of options and
the probability of each option's first token is read after one forward pass (PLAN §9.5, D-63).
The runtime is local (llama.cpp) and loads a file from disk; **nothing in this package talks to a
network or to a hosted model** (D-67 is not active; a test enforces it).
"""
