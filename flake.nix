{
  description = "Semi-automatic memory for coding agents: the agent offers, you decide";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        skill = pkgs.runCommand "semi-auto-memory-skill" { } ''
          cp -r ${./skill} $out
        '';
        semimem = pkgs.runCommand "semimem" { buildInputs = [ pkgs.python3 ]; } ''
          install -Dm755 ${./skill/bin/semimem} $out/bin/semimem
          patchShebangs $out/bin
        '';
      in
      {
        packages = {
          default = semimem;
          inherit semimem skill;
        };

        checks.tests = pkgs.runCommand "semimem-tests" { nativeBuildInputs = [ pkgs.python3 pkgs.git ]; } ''
          cp -r ${self} src && chmod -R u+w src && cd src
          HOME=$TMPDIR python3 -m unittest discover -s tests
          touch $out
        '';

        devShells.default = pkgs.mkShell {
          packages = [ pkgs.python3 pkgs.ruff semimem ];
        };
      });
}
