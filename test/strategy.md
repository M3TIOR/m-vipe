# Test Strategy for `m-vipe`

 * Any kind of error response would be good to test. Max size limits for the
   volatile memory store would be a good place to start

 * Argument expansion is also something that needs tested; at the very least
   we should NOT be expanding paths.

 * POSIX MAX_ARGS needs to be tested and error handled.

 * Should write tests for code-coverage of the variadic argument suite.

 * Maybe fork argparse and improve it. It's a good library.
