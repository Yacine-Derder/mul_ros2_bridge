# Host wall-clock reception of the newline; never firmware acquisition time.
builtin_interfaces/Time received_at
uint16 host_alr_id
# Unique process capture plus connection generation; reboots can repeat epochs.
string capture_session
uint64 connection_generation
uint64 sequence
uint8 AA=1
uint8 FF=4
uint8 kind
uint8 initiator
uint8 responder
uint8 reporter
uint32 cycle
uint64 timestamp_dtu
uint64 epoch
uint32 plan_fingerprint
# Native 40-bit local DW1000 marker. No synchronization or unwrapping.
string clock_domain
string marker
uint8 status
bool valid
bool has_range
uint32 distance_mm
uint32 raw_distance_mm
bool has_power_indicator
bool power_corrected
string reason
string raw_record
