"""Batch mixing system — fill, mix, drain, CIP.

Three ingredient valves meter product into a tank by volume,
then an agitator mixes for a set time, the batch drains out,
and a CIP (clean-in-place) cycle flushes the system.
"""

from plx.framework import (
    BOOL, DINT, REAL, TIME,
    T,
    fb, program, function,
    input_var, output_var, static_var,
    delayed, rising, sustained,
    project,
)

# -- States ----------------------------------------------------------------
IDLE       = 0
FILL_A     = 1
FILL_B     = 2
FILL_C     = 3
MIX        = 4
DRAIN      = 5
CIP_RINSE  = 6
CIP_WASH   = 7
CIP_FINAL  = 8
COMPLETE   = 9
FAULT      = 99


# -------------------------------------------------------------------------
# Valve controller — opens a valve and watches for feedback
# -------------------------------------------------------------------------

@fb
class ValveCtrl:
    cmd_open    = input_var(BOOL, description="Command to open")
    feedback    = input_var(BOOL, description="Open limit switch")
    fault_time  = input_var(TIME, initial=T(3), description="Fault timeout")

    valve_out   = output_var(BOOL, description="Solenoid output")
    is_open     = output_var(BOOL, description="Confirmed open")
    fault       = output_var(BOOL, description="Failed to open in time")

    def logic(self):
        self.valve_out = self.cmd_open

        if self.cmd_open:
            self.is_open = self.feedback
            if delayed(self.cmd_open and not self.feedback, seconds=3):
                self.fault = True
        else:
            self.is_open = False
            self.fault = False


# -------------------------------------------------------------------------
# Volume dosing — counts flow pulses until a target is reached
# -------------------------------------------------------------------------

@fb
class VolumeDose:
    start       = input_var(BOOL, description="Start dosing")
    flow_pulse  = input_var(BOOL, description="Flowmeter pulse input")
    target_vol  = input_var(REAL, description="Target volume (liters)")
    vol_per_pulse = input_var(REAL, initial=0.1, description="Liters per pulse")

    done        = output_var(BOOL, description="Target reached")
    actual_vol  = output_var(REAL, description="Accumulated volume")
    valve_cmd   = output_var(BOOL, description="Open command to valve")

    def logic(self):
        if not self.start:
            self.actual_vol = 0.0
            self.done = False
            self.valve_cmd = False
            return

        if rising(self.flow_pulse):
            self.actual_vol += self.vol_per_pulse

        if self.actual_vol >= self.target_vol:
            self.done = True
            self.valve_cmd = False
        else:
            self.valve_cmd = True


# -------------------------------------------------------------------------
# Main batch sequencer
# -------------------------------------------------------------------------

@program
class BatchMix:
    # --- operator commands ---
    cmd_start   = input_var(BOOL, description="Start batch")
    cmd_reset   = input_var(BOOL, description="Reset after fault/complete")
    cmd_cip     = input_var(BOOL, description="Start CIP cycle")

    # --- field I/O ---
    level       = input_var(REAL, description="Tank level (liters)")
    level_low   = input_var(BOOL, description="Low level switch")
    flow_a      = input_var(BOOL, description="Ingredient A flow pulse")
    flow_b      = input_var(BOOL, description="Ingredient B flow pulse")
    flow_c      = input_var(BOOL, description="Ingredient C flow pulse")

    # --- outputs ---
    valve_a     = output_var(BOOL, description="Ingredient A valve")
    valve_b     = output_var(BOOL, description="Ingredient B valve")
    valve_c     = output_var(BOOL, description="Ingredient C valve")
    drain_valve = output_var(BOOL, description="Drain valve")
    cip_valve   = output_var(BOOL, description="CIP supply valve")
    agitator    = output_var(BOOL, description="Mixer motor")

    # --- status ---
    state       = output_var(DINT, description="Current step")
    batch_done  = output_var(BOOL, description="Batch complete")
    cip_done    = output_var(BOOL, description="CIP complete")

    # --- internal ---
    step         = static_var(DINT, initial=0)
    dose_a_start = static_var(BOOL, initial=False)
    dose_b_start = static_var(BOOL, initial=False)
    dose_c_start = static_var(BOOL, initial=False)
    dose_a_done  = static_var(BOOL, initial=False)
    dose_b_done  = static_var(BOOL, initial=False)
    dose_c_done  = static_var(BOOL, initial=False)

    def logic(self):
        # Reset command returns to idle from complete or fault
        if self.cmd_reset:
            self.step = IDLE
            self.batch_done = False
            self.cip_done = False

        # Default outputs off
        self.agitator = False
        self.drain_valve = False
        self.cip_valve = False
        self.dose_a_start = False
        self.dose_b_start = False
        self.dose_c_start = False

        match self.step:
            # ---- idle ------------------------------------------------
            case 0:
                if rising(self.cmd_start):
                    self.step = FILL_A
                elif rising(self.cmd_cip):
                    self.step = CIP_RINSE

            # ---- fill ingredient A -----------------------------------
            case 1:
                self.dose_a_start = True
                if self.dose_a_done:
                    self.step = FILL_B

            # ---- fill ingredient B -----------------------------------
            case 2:
                self.dose_b_start = True
                if self.dose_b_done:
                    self.step = FILL_C

            # ---- fill ingredient C -----------------------------------
            case 3:
                self.dose_c_start = True
                if self.dose_c_done:
                    self.step = MIX

            # ---- mix for 30 seconds ----------------------------------
            case 4:
                self.agitator = True
                if delayed(self.agitator, seconds=30):
                    self.step = DRAIN

            # ---- drain until low level -------------------------------
            case 5:
                self.drain_valve = True
                self.agitator = True
                if self.level_low:
                    self.step = COMPLETE

            # ---- CIP rinse -------------------------------------------
            case 6:
                self.cip_valve = True
                self.drain_valve = True
                if delayed(self.cip_valve, seconds=60):
                    self.step = CIP_WASH

            # ---- CIP wash (with agitation) ---------------------------
            case 7:
                self.cip_valve = True
                self.drain_valve = True
                self.agitator = True
                if delayed(self.agitator, seconds=120):
                    self.step = CIP_FINAL

            # ---- CIP final rinse -------------------------------------
            case 8:
                self.cip_valve = True
                self.drain_valve = True
                if delayed(self.cip_valve, seconds=60):
                    self.step = COMPLETE

            # ---- complete --------------------------------------------
            case 9:
                self.batch_done = True
                self.cip_done = True

        self.state = self.step


# -------------------------------------------------------------------------
# Assemble project
# -------------------------------------------------------------------------

proj = project("BatchMixPlant", pous=[ValveCtrl, VolumeDose, BatchMix])


if __name__ == "__main__":
    import json

    ir = proj.compile()
    print(f"Project: {ir.name}")
    print(f"POUs:    {len(ir.pous)}")
    for pou in ir.pous:
        iface = pou.interface
        n_stmts = sum(len(n.statements) for n in pou.networks)
        print(f"  {pou.pou_type.value:<20s} {pou.name}")
        print(f"    inputs={len(iface.input_vars)}  outputs={len(iface.output_vars)}  "
              f"statics={len(iface.static_vars)}  temps={len(iface.temp_vars)}  "
              f"statements={n_stmts}")
    print()
    print(json.dumps(ir.model_dump(), indent=2)[:2000])
    print("...")
