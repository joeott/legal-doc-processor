#!/bin/bash
# Test execution script for legal document processor

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check prerequisites
check_prerequisites() {
    print_status "Checking prerequisites..."
    
    if ! command_exists pytest; then
        print_error "pytest not found. Install with: pip install pytest pytest-mock pytest-cov"
        exit 1
    fi
    
    if [ ! -f "load_env.sh" ]; then
        print_warning "load_env.sh not found. Some tests may fail without proper environment."
    fi
    
    print_success "Prerequisites check complete"
}

# Load environment if available
load_environment() {
    if [ -f "load_env.sh" ]; then
        print_status "Loading environment variables..."
        source load_env.sh
        print_success "Environment loaded"
    else
        print_warning "Environment file not found, using defaults"
        export SKIP_CONFORMANCE_CHECK=true
        export USE_MINIMAL_MODELS=true
    fi
}

# Run specific test category
run_test_category() {
    local category=$1
    local description=$2
    
    print_status "Running $description..."
    
    if pytest tests/$category/ -v --tb=short; then
        print_success "$description completed successfully"
        return 0
    else
        print_error "$description failed"
        return 1
    fi
}

# Run tests with coverage
run_with_coverage() {
    print_status "Running tests with coverage analysis..."
    
    pytest tests/ \
        --cov=scripts \
        --cov-report=html \
        --cov-report=term-missing \
        --cov-fail-under=70 \
        -v
    
    if [ $? -eq 0 ]; then
        print_success "Coverage analysis complete. Report saved to htmlcov/"
    else
        print_error "Coverage analysis failed or coverage below threshold"
        return 1
    fi
}

# Main test execution
main() {
    local test_type=${1:-"all"}
    
    echo "==============================================="
    echo "  Legal Document Processor - Test Runner"
    echo "==============================================="
    echo
    
    check_prerequisites
    load_environment
    
    echo
    print_status "Starting test execution: $test_type"
    echo
    
    case $test_type in
        "unit")
            run_test_category "unit" "Unit Tests"
            ;;
        "integration")
            run_test_category "integration" "Integration Tests"
            ;;
        "e2e")
            run_test_category "e2e" "End-to-End Tests"
            ;;
        "fast")
            print_status "Running fast tests only (excluding slow tests)..."
            pytest tests/ -v --tb=short -m "not slow"
            ;;
        "slow")
            print_status "Running slow tests only..."
            pytest tests/ -v --tb=short -m "slow"
            ;;
        "aws")
            print_status "Running tests requiring AWS credentials..."
            pytest tests/ -v --tb=short -m "requires_aws"
            ;;
        "coverage")
            run_with_coverage
            ;;
        "all")
            print_status "Running all test categories..."
            
            # Run unit tests first (fastest)
            if ! run_test_category "unit" "Unit Tests"; then
                print_error "Unit tests failed. Stopping execution."
                exit 1
            fi
            
            echo
            
            # Run integration tests
            if ! run_test_category "integration" "Integration Tests"; then
                print_error "Integration tests failed. Stopping execution."
                exit 1
            fi
            
            echo
            
            # Run E2E tests (slowest, most likely to fail)
            if ! run_test_category "e2e" "End-to-End Tests"; then
                print_error "E2E tests failed."
                exit 1
            fi
            
            print_success "All test categories completed successfully!"
            ;;
        *)
            echo "Usage: $0 [unit|integration|e2e|fast|slow|aws|coverage|all]"
            echo
            echo "Test Categories:"
            echo "  unit         - Run unit tests (fast, isolated)"
            echo "  integration  - Run integration tests (medium speed)"
            echo "  e2e          - Run end-to-end tests (slow, full pipeline)"
            echo "  fast         - Run all tests except slow ones"
            echo "  slow         - Run only slow tests"
            echo "  aws          - Run tests requiring AWS credentials"
            echo "  coverage     - Run tests with coverage analysis"
            echo "  all          - Run all test categories (default)"
            echo
            echo "Examples:"
            echo "  $0                    # Run all tests"
            echo "  $0 unit              # Run only unit tests"
            echo "  $0 fast              # Run all tests except slow ones"
            echo "  $0 coverage          # Run with coverage analysis"
            exit 1
            ;;
    esac
    
    echo
    print_success "Test execution completed: $test_type"
    echo "==============================================="
}

# Run main function with all arguments
main "$@"