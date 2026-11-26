"""Structural routing for versioned mathematical problem families."""

from .commitment_compiler import compile_commitment, compiler_for
from .commitment_ir import UnitCommitment
from .commitment_solver import solve_commitment, verify_commitment
from .math_program_ir import MathematicalProgram
from .math_program_solver import solve_program, verify_result
from .nonlinear_ir import NonlinearProgram
from .nonlinear_solver import solve_nonlinear, verify_nonlinear


def parse_program(raw):
    if isinstance(raw, UnitCommitment) or isinstance(raw, dict) and raw.get("family") == "unit_commitment":
        return UnitCommitment.model_validate(raw)
    if isinstance(raw, NonlinearProgram) or isinstance(raw, dict) and raw.get("family") == "polynomial_nlp":
        return NonlinearProgram.model_validate(raw)
    return MathematicalProgram.model_validate(raw)


def solve(spec):
    spec = parse_program(spec)
    if isinstance(spec, UnitCommitment):
        return solve_commitment(spec)
    return solve_nonlinear(spec) if isinstance(spec, NonlinearProgram) else solve_program(spec)


def verify(spec, result):
    spec = parse_program(spec)
    if isinstance(spec, UnitCommitment):
        return verify_commitment(spec, result)
    return verify_nonlinear(spec, result) if isinstance(spec, NonlinearProgram) else verify_result(spec, result)


def reservation_for(spec):
    spec = parse_program(spec)
    reservation = {"program_sha256": spec.sha256(), "route": spec.route(), "time_limit_s": spec.time_limit_s}
    if isinstance(spec, UnitCommitment):
        reservation.update(node_limit=spec.node_limit, compiler=compiler_for(spec),
                           compiled_program_sha256=compile_commitment(spec).sha256())
    elif isinstance(spec, NonlinearProgram):
        reservation.update(max_iterations=spec.max_iterations, max_evaluations=spec.max_evaluations)
        if spec.analysis is not None:
            reservation["analysis_version"] = spec.analysis.schema_version
    else:
        reservation["node_limit"] = spec.node_limit
    return reservation


def objective_unit(spec):
    spec = parse_program(spec)
    return spec.currency if isinstance(spec, UnitCommitment) else spec.objective.unit
