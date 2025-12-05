import csv
import io
from datetime import datetime, timedelta
from flask import render_template, redirect, url_for, flash, request, Response, make_response
from flask_login import login_user, logout_user, login_required, current_user
from app import app, db, login_manager
from models import User, Product, Category, Supplier, Transaction
from sqlalchemy import or_, and_, func
from functools import wraps


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            flash('Admin access required.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def create_default_admin():
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin = User(username='admin', email='admin@inventory.local', role='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()

def create_default_staff():
    staff = User.query.filter_by(username='staff').first()
    if not staff:
        staff = User(
            username='staff',
            email='staff@inventory.local',
            role='staff'
        )
        staff.set_password('staff123')
        db.session.add(staff)
        db.session.commit()


with app.app_context():
    create_default_admin()

with app.app_context():
    create_default_staff()

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            next_page = request.args.get('next')
            flash('Login successful!', 'success')
            return redirect(next_page or url_for('dashboard'))
        flash('Invalid username or password', 'error')
    
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    total_products = Product.query.count()
    total_stock = db.session.query(db.func.sum(Product.quantity)).scalar() or 0
    low_stock_count = Product.query.filter(Product.quantity <= Product.reorder_level).count()
    out_of_stock_count = Product.query.filter(Product.quantity == 0).count()
    
    low_stock_products = Product.query.filter(
        Product.quantity <= Product.reorder_level
    ).order_by(Product.quantity.asc()).limit(5).all()
    
    recent_transactions = Transaction.query.order_by(
        Transaction.created_at.desc()
    ).limit(10).all()
    
    return render_template('dashboard.html',
                           total_products=total_products,
                           total_stock=total_stock,
                           low_stock_count=low_stock_count,
                           out_of_stock_count=out_of_stock_count,
                           low_stock_products=low_stock_products,
                           recent_transactions=recent_transactions)


@app.route('/products')
@login_required
def products():
    search = request.args.get('search', '')
    category_id = request.args.get('category', type=int)
    sort_by = request.args.get('sort', 'name')
    order = request.args.get('order', 'asc')
    
    query = Product.query
    
    if search:
        query = query.filter(
            or_(
                Product.name.ilike(f'%{search}%'),
                Product.sku.ilike(f'%{search}%')
            )
        )
    
    if category_id:
        query = query.filter(Product.category_id == category_id)
    
    sort_column = getattr(Product, sort_by, Product.name)
    if order == 'desc':
        query = query.order_by(sort_column.desc())
    else:
        query = query.order_by(sort_column.asc())
    
    products_list = query.all()
    categories = Category.query.order_by(Category.name).all()
    
    return render_template('products.html',
                           products=products_list,
                           categories=categories,
                           search=search,
                           category_id=category_id,
                           sort_by=sort_by,
                           order=order)


@app.route('/products/add', methods=['GET', 'POST'])
@login_required
def add_product():
    if request.method == 'POST':
        name = request.form.get('name')
        sku = request.form.get('sku')
        description = request.form.get('description')
        purchase_price = float(request.form.get('purchase_price', 0))
        selling_price = float(request.form.get('selling_price', 0))
        quantity = int(request.form.get('quantity', 0))
        reorder_level = int(request.form.get('reorder_level', 10))
        category_id = request.form.get('category_id') or None
        supplier_id = request.form.get('supplier_id') or None
        
        existing = Product.query.filter_by(sku=sku).first()
        if existing:
            flash('A product with this SKU already exists.', 'error')
        else:
            product = Product(
                name=name,
                sku=sku,
                description=description,
                purchase_price=purchase_price,
                selling_price=selling_price,
                quantity=quantity,
                reorder_level=reorder_level,
                category_id=category_id if category_id else None,
                supplier_id=supplier_id if supplier_id else None
            )
            db.session.add(product)
            
            if quantity > 0:
                transaction = Transaction(
                    product=product,
                    type='purchase',
                    quantity=quantity,
                    notes='Initial stock',
                    user_id=current_user.id
                )
                db.session.add(transaction)
            
            db.session.commit()
            flash('Product added successfully!', 'success')
            return redirect(url_for('products'))
    
    categories = Category.query.order_by(Category.name).all()
    suppliers = Supplier.query.order_by(Supplier.name).all()
    return render_template('product_form.html',
                           product=None,
                           categories=categories,
                           suppliers=suppliers,
                           action='Add')


@app.route('/products/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_product(id):
    product = Product.query.get_or_404(id)
    
    if request.method == 'POST':
        product.name = request.form.get('name')
        new_sku = request.form.get('sku')
        
        if new_sku != product.sku:
            existing = Product.query.filter_by(sku=new_sku).first()
            if existing:
                flash('A product with this SKU already exists.', 'error')
                categories = Category.query.order_by(Category.name).all()
                suppliers = Supplier.query.order_by(Supplier.name).all()
                return render_template('product_form.html',
                                       product=product,
                                       categories=categories,
                                       suppliers=suppliers,
                                       action='Edit')
        
        product.sku = new_sku
        product.description = request.form.get('description')
        product.purchase_price = float(request.form.get('purchase_price', 0))
        product.selling_price = float(request.form.get('selling_price', 0))
        product.reorder_level = int(request.form.get('reorder_level', 10))
        category_id = request.form.get('category_id')
        supplier_id = request.form.get('supplier_id')
        product.category_id = int(category_id) if category_id else None
        product.supplier_id = int(supplier_id) if supplier_id else None
        
        db.session.commit()
        flash('Product updated successfully!', 'success')
        return redirect(url_for('products'))
    
    categories = Category.query.order_by(Category.name).all()
    suppliers = Supplier.query.order_by(Supplier.name).all()
    return render_template('product_form.html',
                           product=product,
                           categories=categories,
                           suppliers=suppliers,
                           action='Edit')


@app.route('/products/<int:id>/delete', methods=['POST'])
@login_required
def delete_product(id):
    if not current_user.is_admin():
        flash('Only admins can delete products.', 'error')
        return redirect(url_for('products'))
    
    product = Product.query.get_or_404(id)
    Transaction.query.filter_by(product_id=id).delete()
    db.session.delete(product)
    db.session.commit()
    flash('Product deleted successfully!', 'success')
    return redirect(url_for('products'))


@app.route('/products/<int:id>/stock', methods=['GET', 'POST'])
@login_required
def update_stock(id):
    product = Product.query.get_or_404(id)
    
    if request.method == 'POST':
        action = request.form.get('action')
        quantity = int(request.form.get('quantity', 0))
        notes = request.form.get('notes', '')
        
        if quantity <= 0:
            flash('Quantity must be greater than 0.', 'error')
        elif action == 'sale' and quantity > product.quantity:
            flash('Cannot sell more than available stock.', 'error')
        else:
            if action == 'purchase':
                product.quantity += quantity
                transaction_type = 'purchase'
            else:
                product.quantity -= quantity
                transaction_type = 'sale'
            
            transaction = Transaction(
                product_id=product.id,
                type=transaction_type,
                quantity=quantity,
                notes=notes,
                user_id=current_user.id
            )
            db.session.add(transaction)
            db.session.commit()
            
            flash(f'Stock {action} recorded successfully!', 'success')
            return redirect(url_for('products'))
    
    return render_template('stock_form.html', product=product)


@app.route('/low-stock')
@login_required
def low_stock():
    products_list = Product.query.filter(
        Product.quantity <= Product.reorder_level
    ).order_by(Product.quantity.asc()).all()
    
    return render_template('low_stock.html', products=products_list)


@app.route('/categories')
@login_required
def categories():
    categories_list = Category.query.order_by(Category.name).all()
    return render_template('categories.html', categories=categories_list)


@app.route('/categories/add', methods=['POST'])
@login_required
def add_category():
    name = request.form.get('name')
    description = request.form.get('description')
    
    existing = Category.query.filter_by(name=name).first()
    if existing:
        flash('A category with this name already exists.', 'error')
    else:
        category = Category(name=name, description=description)
        db.session.add(category)
        db.session.commit()
        flash('Category added successfully!', 'success')
    
    return redirect(url_for('categories'))


@app.route('/categories/<int:id>/edit', methods=['POST'])
@login_required
def edit_category(id):
    category = Category.query.get_or_404(id)
    name = request.form.get('name')
    
    if name != category.name:
        existing = Category.query.filter_by(name=name).first()
        if existing:
            flash('A category with this name already exists.', 'error')
            return redirect(url_for('categories'))
    
    category.name = name
    category.description = request.form.get('description')
    db.session.commit()
    flash('Category updated successfully!', 'success')
    return redirect(url_for('categories'))


@app.route('/categories/<int:id>/delete', methods=['POST'])
@login_required
def delete_category(id):
    if not current_user.is_admin():
        flash('Only admins can delete categories.', 'error')
        return redirect(url_for('categories'))
    
    category = Category.query.get_or_404(id)
    
    if category.products.count() > 0:
        flash('Cannot delete category with associated products.', 'error')
    else:
        db.session.delete(category)
        db.session.commit()
        flash('Category deleted successfully!', 'success')
    
    return redirect(url_for('categories'))


@app.route('/suppliers')
@login_required
def suppliers():
    suppliers_list = Supplier.query.order_by(Supplier.name).all()
    return render_template('suppliers.html', suppliers=suppliers_list)


@app.route('/suppliers/add', methods=['GET', 'POST'])
@login_required
def add_supplier():
    if request.method == 'POST':
        supplier = Supplier(
            name=request.form.get('name'),
            contact_name=request.form.get('contact_name'),
            email=request.form.get('email'),
            phone=request.form.get('phone'),
            address=request.form.get('address')
        )
        db.session.add(supplier)
        db.session.commit()
        flash('Supplier added successfully!', 'success')
        return redirect(url_for('suppliers'))
    
    return render_template('supplier_form.html', supplier=None, action='Add')


@app.route('/suppliers/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_supplier(id):
    supplier = Supplier.query.get_or_404(id)
    
    if request.method == 'POST':
        supplier.name = request.form.get('name')
        supplier.contact_name = request.form.get('contact_name')
        supplier.email = request.form.get('email')
        supplier.phone = request.form.get('phone')
        supplier.address = request.form.get('address')
        db.session.commit()
        flash('Supplier updated successfully!', 'success')
        return redirect(url_for('suppliers'))
    
    return render_template('supplier_form.html', supplier=supplier, action='Edit')


@app.route('/suppliers/<int:id>/delete', methods=['POST'])
@login_required
def delete_supplier(id):
    if not current_user.is_admin():
        flash('Only admins can delete suppliers.', 'error')
        return redirect(url_for('suppliers'))
    
    supplier = Supplier.query.get_or_404(id)
    
    if supplier.products.count() > 0:
        flash('Cannot delete supplier with associated products.', 'error')
    else:
        db.session.delete(supplier)
        db.session.commit()
        flash('Supplier deleted successfully!', 'success')
    
    return redirect(url_for('suppliers'))


@app.route('/transactions')
@login_required
def transactions():
    filter_type = request.args.get('type', 'all')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    product_id = request.args.get('product_id', type=int)
    
    query = Transaction.query
    
    if filter_type == 'purchase':
        query = query.filter(Transaction.type == 'purchase')
    elif filter_type == 'sale':
        query = query.filter(Transaction.type == 'sale')
    
    if date_from:
        try:
            from_date = datetime.strptime(date_from, '%Y-%m-%d')
            query = query.filter(Transaction.created_at >= from_date)
        except ValueError:
            pass
    
    if date_to:
        try:
            to_date = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(Transaction.created_at < to_date)
        except ValueError:
            pass
    
    if product_id:
        query = query.filter(Transaction.product_id == product_id)
    
    transactions_list = query.order_by(Transaction.created_at.desc()).all()
    products = Product.query.order_by(Product.name).all()
    
    return render_template('transactions.html',
                           transactions=transactions_list,
                           products=products,
                           filter_type=filter_type,
                           date_from=date_from,
                           date_to=date_to,
                           product_id=product_id)


@app.route('/export/products')
@login_required
def export_products():
    products_list = Product.query.order_by(Product.name).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow(['ID', 'Name', 'SKU', 'Description', 'Category', 'Supplier', 
                     'Purchase Price', 'Selling Price', 'Quantity', 'Reorder Level', 'Created At'])
    
    for p in products_list:
        writer.writerow([
            p.id,
            p.name,
            p.sku,
            p.description or '',
            p.category.name if p.category else '',
            p.supplier.name if p.supplier else '',
            p.purchase_price,
            p.selling_price,
            p.quantity,
            p.reorder_level,
            p.created_at.strftime('%Y-%m-%d %H:%M:%S')
        ])
    
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = 'attachment; filename=products_export.csv'
    return response


@app.route('/export/transactions')
@login_required
def export_transactions():
    filter_type = request.args.get('type', 'all')
    
    query = Transaction.query
    if filter_type == 'purchase':
        query = query.filter(Transaction.type == 'purchase')
    elif filter_type == 'sale':
        query = query.filter(Transaction.type == 'sale')
    
    transactions_list = query.order_by(Transaction.created_at.desc()).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow(['ID', 'Date', 'Product', 'SKU', 'Type', 'Quantity', 'Notes', 'User'])
    
    for t in transactions_list:
        writer.writerow([
            t.id,
            t.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            t.product.name,
            t.product.sku,
            t.type.capitalize(),
            t.quantity,
            t.notes or '',
            t.user.username if t.user else 'System'
        ])
    
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=transactions_{filter_type}_export.csv'
    return response


@app.route('/import/products', methods=['GET', 'POST'])
@login_required
@admin_required
def import_products():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file selected.', 'error')
            return redirect(url_for('import_products'))
        
        file = request.files['file']
        if file.filename == '':
            flash('No file selected.', 'error')
            return redirect(url_for('import_products'))
        
        if not file.filename.endswith('.csv'):
            flash('Please upload a CSV file.', 'error')
            return redirect(url_for('import_products'))
        
        try:
            stream = io.StringIO(file.stream.read().decode('utf-8'))
            reader = csv.DictReader(stream)
            
            imported = 0
            skipped = 0
            errors = []
            
            for row in reader:
                try:
                    sku = row.get('SKU', row.get('sku', '')).strip()
                    if not sku:
                        skipped += 1
                        continue
                    
                    existing = Product.query.filter_by(sku=sku).first()
                    if existing:
                        skipped += 1
                        errors.append(f"SKU '{sku}' already exists")
                        continue
                    
                    name = row.get('Name', row.get('name', '')).strip()
                    if not name:
                        skipped += 1
                        continue
                    
                    category_name = row.get('Category', row.get('category', '')).strip()
                    category = None
                    if category_name:
                        category = Category.query.filter_by(name=category_name).first()
                        if not category:
                            category = Category(name=category_name)
                            db.session.add(category)
                            db.session.flush()
                    
                    supplier_name = row.get('Supplier', row.get('supplier', '')).strip()
                    supplier = None
                    if supplier_name:
                        supplier = Supplier.query.filter_by(name=supplier_name).first()
                        if not supplier:
                            supplier = Supplier(name=supplier_name)
                            db.session.add(supplier)
                            db.session.flush()
                    
                    product = Product(
                        name=name,
                        sku=sku,
                        description=row.get('Description', row.get('description', '')),
                        purchase_price=float(row.get('Purchase Price', row.get('purchase_price', 0)) or 0),
                        selling_price=float(row.get('Selling Price', row.get('selling_price', 0)) or 0),
                        quantity=int(row.get('Quantity', row.get('quantity', 0)) or 0),
                        reorder_level=int(row.get('Reorder Level', row.get('reorder_level', 10)) or 10),
                        category_id=category.id if category else None,
                        supplier_id=supplier.id if supplier else None
                    )
                    db.session.add(product)
                    imported += 1
                    
                except Exception as e:
                    skipped += 1
                    errors.append(str(e))
            
            db.session.commit()
            
            if imported > 0:
                flash(f'Successfully imported {imported} products.', 'success')
            if skipped > 0:
                flash(f'Skipped {skipped} rows (duplicates or invalid data).', 'warning')
                
        except Exception as e:
            db.session.rollback()
            flash(f'Error importing file: {str(e)}', 'error')
        
        return redirect(url_for('products'))
    
    return render_template('import_products.html')


@app.route('/api/dashboard-stats')
@login_required
def dashboard_stats():
    days = 30
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    
    purchases = db.session.query(
        func.date(Transaction.created_at).label('date'),
        func.sum(Transaction.quantity).label('total')
    ).filter(
        Transaction.type == 'purchase',
        Transaction.created_at >= start_date
    ).group_by(func.date(Transaction.created_at)).all()
    
    sales = db.session.query(
        func.date(Transaction.created_at).label('date'),
        func.sum(Transaction.quantity).label('total')
    ).filter(
        Transaction.type == 'sale',
        Transaction.created_at >= start_date
    ).group_by(func.date(Transaction.created_at)).all()
    
    dates = []
    purchase_data = []
    sale_data = []
    
    purchase_dict = {str(p.date): p.total for p in purchases}
    sale_dict = {str(s.date): s.total for s in sales}
    
    for i in range(days):
        date = start_date + timedelta(days=i)
        date_str = date.strftime('%Y-%m-%d')
        dates.append(date.strftime('%b %d'))
        purchase_data.append(purchase_dict.get(date_str, 0))
        sale_data.append(sale_dict.get(date_str, 0))
    
    return {
        'labels': dates,
        'purchases': purchase_data,
        'sales': sale_data
    }
