module ripple_carry_adder #(
    parameter WIDTH = 4
) (
    input  wire [3:0] a,
    input  wire [3:0] b,
    input  wire       cin,
    output wire [3:0] sum,
    output wire       cout
);

    // Internal carry chain: carry[0] = cin, carry[4] = cout
    wire [4:0] carry;

    // One full adder per bit slice; carry ripples LSB -> MSB
    wire [3:0] prop;    // a[i] ^ b[i]
    wire [3:0] gen;     // a[i] & b[i]

    assign carry[0] = cin;

    assign gen  = a & b;
    assign prop = a ^ b;

    // Full adder slice 0
    assign sum[0]   = prop[0] ^ carry[0];
    assign carry[1] = gen[0] | (prop[0] & carry[0]);

    // Full adder slice 1
    assign sum[1]   = prop[1] ^ carry[1];
    assign carry[2] = gen[1] | (prop[1] & carry[1]);

    // Full adder slice 2
    assign sum[2]   = prop[2] ^ carry[2];
    assign carry[3] = gen[2] | (prop[2] & carry[2]);

    // Full adder slice 3
    assign sum[3]   = prop[3] ^ carry[3];
    assign carry[4] = gen[3] | (prop[3] & carry[3]);

    // Carry out of the most significant bit position
    assign cout = carry[4];

endmodule