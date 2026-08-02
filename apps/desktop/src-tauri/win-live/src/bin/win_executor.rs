//! The governed executor image — the driver spawns it to produce the turn's EXACT reply bytes on stdout. Its
//! output is content-addressed into the protected store and digest-gated by the isolated-signer envelope, so
//! the bytes are what the whole chain binds to. (In the hardened milestone this runs under a restricted token
//! in session 0; here it is the plain output producer that proves the chain.)

use std::io::Write;

fn main() {
    let out = b"BROPS windows governed output v1";
    let mut stdout = std::io::stdout();
    stdout.write_all(out).expect("write output");
    stdout.flush().expect("flush");
}
